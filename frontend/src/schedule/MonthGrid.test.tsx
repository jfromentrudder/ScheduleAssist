/** Tests for the month view.
 *
 * The month is the one span that is not a scaled-down week: no time axis, and
 * the app's own output reduced to a count. These check that it stays that way —
 * a period rendered as a chip here would be a regression, not a feature. */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { MonthGrid } from './MonthGrid'
import type { Schedule, ScheduleEvent, SchedulePeriod } from './types'
import { MONTH_GRID_DAYS, addDays, startOfMonthGridIn, toZoneClock } from './week'

/** August 2026 opens on Monday 27 July — the 1st is a Saturday. */
const GRID_START = startOfMonthGridIn(new Date('2026-08-12T12:00:00Z'), 'UTC')
const MONTH_OF = new Date(2026, 7, 15)
const NOW = new Date('2026-08-12T12:00:00Z')

function gridDays(): Date[] {
  return Array.from({ length: MONTH_GRID_DAYS }, (_, i) =>
    addDays(toZoneClock(GRID_START, 'UTC'), i),
  )
}

function event(over: Partial<ScheduleEvent> = {}): ScheduleEvent {
  return {
    id: 1,
    title: 'Standup',
    description: null,
    event_type: 'one_time',
    source: 'imported',
    availability: 'busy',
    starts_at: '2026-08-12T09:00:00Z',
    ends_at: '2026-08-12T10:00:00Z',
    due_at: null,
    is_all_day: false,
    expected_prep_minutes: null,
    type_locked: false,
    ...over,
  }
}

function period(over: Partial<SchedulePeriod> = {}): SchedulePeriod {
  return {
    id: 10,
    starts_at: '2026-08-12T13:00:00Z',
    ends_at: '2026-08-12T13:50:00Z',
    kind: 'work',
    locked: false,
    events: [{ id: 1, title: 'Essay' }],
    ...over,
  }
}

function schedule(over: Partial<Schedule> = {}): Schedule {
  return {
    start: GRID_START.toISOString(),
    end: GRID_START.toISOString(),
    view: 'generated',
    preferences: {
      workdays: [0, 1, 2, 3, 4],
      day_start: '09:00:00',
      day_end: '17:00:00',
      period_minutes: 50,
      timezone: 'UTC',
      schedule_horizon_days: 5,
    },
    horizon_ends_at: null,
    events: [],
    periods: [],
    ...over,
  }
}

function draw(over: Partial<Schedule> = {}, props: Record<string, unknown> = {}) {
  return render(
    <MonthGrid
      schedule={schedule(over)}
      days={gridDays()}
      monthOf={MONTH_OF}
      now={NOW}
      {...props}
    />,
  )
}

// --- Shape --------------------------------------------------------------

describe('the grid', () => {
  it('draws six rows of seven, so every month is the same height', () => {
    const { container } = draw()

    expect(container.querySelectorAll('.month-cell')).toHaveLength(42)
  })

  it('heads the columns with weekday names, Monday first', () => {
    const { container } = draw()
    const headings = [...container.querySelectorAll('.month-dow')].map(
      (el) => el.textContent,
    )

    expect(headings).toHaveLength(7)
    expect(headings[0]).toMatch(/Mon/)
    expect(headings[6]).toMatch(/Sun/)
  })

  it('dims the days borrowed from the months either side', () => {
    const { container } = draw()
    const outside = container.querySelectorAll('.month-cell.is-outside')

    // 27-31 July leading, and 1-6 September trailing.
    expect(outside).toHaveLength(11)
  })

  it('marks today, and only today', () => {
    const { container } = draw()

    expect(container.querySelectorAll('.month-cell.is-today')).toHaveLength(1)
  })

  it('has no time axis at all', () => {
    const { container } = draw()

    expect(container.querySelector('.week-hours')).toBeNull()
    expect(container.querySelector('.week-scroll')).toBeNull()
  })
})

// --- Content ------------------------------------------------------------

describe('what a cell shows', () => {
  it('renders an event as a chip', () => {
    draw({ events: [event()] })

    expect(screen.getByText('Standup')).toBeInTheDocument()
  })

  it('opens the event when its chip is clicked', async () => {
    const onSelectEvent = vi.fn()
    draw({ events: [event()] }, { onSelectEvent })

    await userEvent.click(screen.getByRole('button', { name: /Standup/ }))

    expect(onSelectEvent).toHaveBeenCalledWith(1)
  })

  it('shows periods as a count, never as chips', () => {
    // The rule the whole view rests on.
    const { container } = draw({ periods: [period()] })

    expect(container.querySelectorAll('.month-chip')).toHaveLength(0)
    expect(screen.getByText('1 period · 50m')).toBeInTheDocument()
  })

  it('says nothing about periods on a day with none', () => {
    const { container } = draw({ periods: [period()] })

    expect(container.querySelectorAll('.month-load')).toHaveLength(1)
  })

  it('marks a deadline as its own kind of chip', () => {
    const { container } = draw({
      events: [
        event({
          title: 'Essay 2',
          event_type: 'deadline',
          starts_at: null,
          ends_at: null,
          due_at: '2026-08-12T17:00:00Z',
        }),
      ],
    })

    expect(container.querySelector('.month-chip.kind-deadline')).not.toBeNull()
  })

  it('counts what did not fit', () => {
    const at = (hour: number) =>
      `2026-08-12T${String(hour).padStart(2, '0')}:00:00Z`
    draw({
      events: Array.from({ length: 5 }, (_, i) =>
        event({ id: i + 1, title: `Thing ${i + 1}`, starts_at: at(i + 8), ends_at: at(i + 9) }),
      ),
    })

    expect(screen.getByText('+2 more')).toBeInTheDocument()
  })
})

// --- Dropping into a day ------------------------------------------------

describe('opening a single day', () => {
  it('makes the date a button when the caller can handle it', () => {
    draw({}, { onSelectDay: vi.fn() })

    expect(
      screen.getByRole('button', { name: /Open Wednesday, August 12/ }),
    ).toBeInTheDocument()
  })

  it('reports the day that was clicked', async () => {
    const onSelectDay = vi.fn()
    draw({}, { onSelectDay })

    await userEvent.click(
      screen.getByRole('button', { name: /Open Wednesday, August 12/ }),
    )

    expect(onSelectDay).toHaveBeenCalledOnce()
    const day = onSelectDay.mock.calls[0][0] as Date
    expect(day.getDate()).toBe(12)
    expect(day.getMonth()).toBe(7)
  })

  it('leaves the date as plain text when there is nothing to open', () => {
    const { container } = draw()
    const first = container.querySelector('.month-cell')!

    expect(within(first as HTMLElement).queryByRole('button')).toBeNull()
  })
})
