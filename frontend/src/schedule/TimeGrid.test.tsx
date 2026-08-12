/** Tests for the time-axis calendar.
 *
 * The grid is the app's main screen and had never been machine-verified: until
 * now the only checks on it were that it compiled. These cover what the markup
 * has to get right — which blocks appear, what is clickable, and the structural
 * cues (today, non-workdays, the settled edge) that carry meaning.
 *
 * It draws whatever days it is handed, so the same component serves the day and
 * week spans; the column count is the only difference between them. */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TimeGrid } from './TimeGrid'
import type { Schedule, ScheduleEvent, SchedulePeriod } from './types'
import { DAYS_IN_WEEK, addDays, toZoneClock } from './week'

/** Monday 10 Aug 2026, the week every fixture below describes. */
const WEEK_START = new Date('2026-08-10T00:00:00Z')
/** Tuesday lunchtime, so "today" is inside the week and not on its edge. */
const NOW = new Date('2026-08-11T12:00:00Z')

function event(over: Partial<ScheduleEvent> = {}): ScheduleEvent {
  return {
    id: 1,
    title: 'Standup',
    description: null,
    event_type: 'one_time',
    source: 'imported',
    availability: 'busy',
    starts_at: '2026-08-10T09:00:00Z',
    ends_at: '2026-08-10T10:00:00Z',
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
    starts_at: '2026-08-10T13:00:00Z',
    ends_at: '2026-08-10T13:50:00Z',
    kind: 'work',
    locked: false,
    events: [{ id: 1, title: 'Essay' }],
    ...over,
  }
}

function schedule(over: Partial<Schedule> = {}): Schedule {
  return {
    start: '2026-08-10T00:00:00Z',
    end: '2026-08-17T00:00:00Z',
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

/** The seven columns of the fixture week, as the page would compute them. */
function weekDays(count = DAYS_IN_WEEK): Date[] {
  return Array.from({ length: count }, (_, i) =>
    addDays(toZoneClock(WEEK_START, 'UTC'), i),
  )
}

function draw(over: Partial<Schedule> = {}, props: Record<string, unknown> = {}) {
  return render(
    <TimeGrid
      schedule={schedule(over)}
      days={weekDays()}
      now={NOW}
      {...props}
    />,
  )
}

// --- Structure ----------------------------------------------------------

describe('the grid itself', () => {
  it('draws seven day columns', () => {
    const { container } = draw()

    expect(container.querySelectorAll('.week-col')).toHaveLength(7)
  })

  it('draws whatever days it is given, so one day is the same component', () => {
    const { container } = render(
      <TimeGrid schedule={schedule()} days={weekDays(1)} now={NOW} />,
    )

    expect(container.querySelectorAll('.week-col')).toHaveLength(1)
    expect(container.querySelectorAll('.week-day-head')).toHaveLength(1)
  })

  it('tells the CSS how many columns to share the width', () => {
    const { container } = render(
      <TimeGrid schedule={schedule()} days={weekDays(1)} now={NOW} />,
    )
    const grid = container.querySelector('.week') as HTMLElement

    expect(grid.style.getPropertyValue('--day-count')).toBe('1')
  })

  it('marks today, and only today', () => {
    const { container } = draw()
    const today = container.querySelectorAll('.week-col.is-today')

    expect(today).toHaveLength(1)
    // Tuesday is the second column.
    expect(container.querySelectorAll('.week-col')[1]).toHaveClass('is-today')
  })

  it('shades the two days the user does not work', () => {
    const { container } = draw()

    expect(container.querySelectorAll('.week-col.is-off')).toHaveLength(2)
  })

  it('follows the workdays preference rather than assuming Mon-Fri', () => {
    const { container } = draw({
      preferences: { ...schedule().preferences, workdays: [0, 1, 2] },
    })

    expect(container.querySelectorAll('.week-col.is-off')).toHaveLength(4)
  })

  it('shows the all-day strip only when something is in it', () => {
    const { container: without } = draw()
    expect(without.querySelector('.week-allday')).toBeNull()

    const { container: with_ } = draw({
      events: [
        event({
          is_all_day: true,
          title: 'Reading day',
          availability: 'free',
          starts_at: '2026-08-10T00:00:00Z',
          ends_at: '2026-08-11T00:00:00Z',
        }),
      ],
    })
    expect(with_.querySelector('.week-allday')).not.toBeNull()
    expect(screen.getByText('Reading day')).toBeInTheDocument()
  })
})

// --- Blocks -------------------------------------------------------------

describe('blocks', () => {
  it('renders a commitment from the calendar', () => {
    draw({ events: [event()] })

    expect(screen.getByText('Standup')).toBeInTheDocument()
    expect(screen.getByText('From calendar')).toBeInTheDocument()
  })

  it('distinguishes an event the user added themselves', () => {
    draw({ events: [event({ source: 'manual', title: 'Coffee' })] })

    expect(screen.getByText('Added by you')).toBeInTheDocument()
  })

  it('opens an event when its block is clicked', async () => {
    const onSelectEvent = vi.fn()
    draw({ events: [event()] }, { onSelectEvent })

    await userEvent.click(screen.getByRole('button', { name: /Standup/ }))

    expect(onSelectEvent).toHaveBeenCalledWith(1)
  })

  it('is not clickable when no handler is given', () => {
    draw({ events: [event()] })

    expect(screen.queryByRole('button', { name: /Standup/ })).toBeNull()
  })

  it('gives a generated period the settled edge only when it is locked', () => {
    const { container: open } = draw({ periods: [period()] })
    expect(open.querySelector('.block.kind-period')).not.toHaveClass('is-locked')

    const { container: settled } = draw({ periods: [period({ locked: true })] })
    expect(settled.querySelector('.block.kind-period')).toHaveClass('is-locked')
  })

  it('labels a period with the deadline it serves', () => {
    draw({ periods: [period()] })

    expect(screen.getByText('Essay')).toBeInTheDocument()
    expect(screen.getByText('Work period')).toBeInTheDocument()
  })

  it('opens the deadline behind a period', async () => {
    const onSelectEvent = vi.fn()
    draw({ periods: [period()] }, { onSelectEvent })

    await userEvent.click(screen.getByRole('button', { name: /Essay/ }))

    expect(onSelectEvent).toHaveBeenCalledWith(1)
  })

  it('renders a meal break as held-clear time', () => {
    draw({ periods: [period({ kind: 'meal', events: [] })] })

    expect(screen.getByText('Meal break')).toBeInTheDocument()
    expect(screen.getByText('Kept clear')).toBeInTheDocument()
  })
})

// --- Deleting a period --------------------------------------------------

describe('deleting a period', () => {
  it('offers a delete control on a generated block', () => {
    draw({ periods: [period()] }, { onDeletePeriod: vi.fn() })

    expect(
      screen.getByRole('button', { name: 'Delete Essay' }),
    ).toBeInTheDocument()
  })

  it('offers none when the caller cannot handle it', () => {
    draw({ periods: [period()] })

    expect(screen.queryByRole('button', { name: /^Delete/ })).toBeNull()
  })

  it('never offers one on an event, which is not generated', () => {
    draw({ events: [event()] }, { onDeletePeriod: vi.fn() })

    expect(screen.queryByRole('button', { name: /^Delete/ })).toBeNull()
  })

  it('reports the period id and that it is not settled', async () => {
    const onDeletePeriod = vi.fn()
    draw({ periods: [period()] }, { onDeletePeriod })

    await userEvent.click(screen.getByRole('button', { name: 'Delete Essay' }))

    expect(onDeletePeriod).toHaveBeenCalledWith(10, false)
  })

  it('reports a settled period as settled, so the caller can warn', async () => {
    const onDeletePeriod = vi.fn()
    draw({ periods: [period({ locked: true })] }, { onDeletePeriod })

    await userEvent.click(screen.getByRole('button', { name: 'Delete Essay' }))

    expect(onDeletePeriod).toHaveBeenCalledWith(10, true)
  })

  it('lets a meal break be deleted too', async () => {
    const onDeletePeriod = vi.fn()
    draw({ periods: [period({ kind: 'meal', events: [] })] }, { onDeletePeriod })

    await userEvent.click(
      screen.getByRole('button', { name: 'Delete Meal break' }),
    )

    expect(onDeletePeriod).toHaveBeenCalledWith(10, false)
  })

  it('keeps deleting separate from opening the deadline', async () => {
    // The two controls live in one block, so a click on either must not
    // trigger the other — the reason a period is not itself a button.
    const onSelectEvent = vi.fn()
    const onDeletePeriod = vi.fn()
    draw({ periods: [period()] }, { onSelectEvent, onDeletePeriod })

    await userEvent.click(screen.getByRole('button', { name: 'Delete Essay' }))

    expect(onDeletePeriod).toHaveBeenCalledOnce()
    expect(onSelectEvent).not.toHaveBeenCalled()
  })
})

// --- Deadlines and work windows -----------------------------------------

describe('deadlines', () => {
  const deadline = event({
    id: 7,
    title: 'Essay 2',
    event_type: 'deadline',
    starts_at: null,
    ends_at: null,
    due_at: '2026-08-12T17:00:00Z',
  })

  it('flags a deadline on its due day', () => {
    draw({ events: [deadline] })

    expect(screen.getByText('Due: Essay 2')).toBeInTheDocument()
  })

  it('opens the deadline from its flag', async () => {
    const onSelectEvent = vi.fn()
    draw({ events: [deadline] }, { onSelectEvent })

    await userEvent.click(screen.getByRole('button', { name: 'Due: Essay 2' }))

    expect(onSelectEvent).toHaveBeenCalledWith(7)
  })
})

describe('work windows', () => {
  const shift = event({
    id: 3,
    title: 'At work',
    availability: 'work_window',
    starts_at: '2026-08-10T10:00:00Z',
    ends_at: '2026-08-10T16:00:00Z',
  })

  it('renders a shift as a background rather than a block', () => {
    const { container } = draw({ events: [shift] })

    expect(container.querySelector('.work-window')).not.toBeNull()
    // It must not take a lane, or periods inside it would render at half width.
    expect(container.querySelectorAll('.block')).toHaveLength(0)
  })

  it('opens the shift when clicked', async () => {
    const onSelectEvent = vi.fn()
    draw({ events: [shift] }, { onSelectEvent })

    await userEvent.click(screen.getByRole('button', { name: 'At work' }))

    expect(onSelectEvent).toHaveBeenCalledWith(3)
  })
})

// --- The commitment horizon --------------------------------------------

describe('the horizon rule', () => {
  it('marks the first open day when settled days precede it', () => {
    const { container } = draw({
      // Local midnight Wednesday: Mon and Tue are settled, Wed is not.
      horizon_ends_at: '2026-08-12T00:00:00Z',
    })
    const columns = container.querySelectorAll('.week-col')

    expect(columns[2]).toHaveClass('is-horizon')
    expect(container.querySelectorAll('.week-col.is-horizon')).toHaveLength(1)
  })

  it('draws nothing when the whole week is already open', () => {
    const { container } = draw({ horizon_ends_at: '2026-08-03T00:00:00Z' })

    expect(container.querySelector('.is-horizon')).toBeNull()
  })

  it('draws nothing in the calendar view, which settles nothing', () => {
    const { container } = draw({ view: 'calendar', horizon_ends_at: null })

    expect(container.querySelector('.is-horizon')).toBeNull()
  })

  it('does not draw against the left edge of a fully settled week', () => {
    // Every day in view is settled, so there is no boundary inside the week.
    const { container } = draw({ horizon_ends_at: '2026-08-20T00:00:00Z' })

    expect(container.querySelector('.is-horizon')).toBeNull()
  })
})

// --- The current-time line ---------------------------------------------

describe('the now line', () => {
  it('appears in today\'s column, and only there', () => {
    const { container } = draw()
    const today = container.querySelector('.week-col.is-today')!

    expect(within(today as HTMLElement).getByLabelText('Current time')).toBeInTheDocument()
    expect(container.querySelectorAll('.now-line')).toHaveLength(1)
  })

  it('shows at any hour, since the whole day is drawn', () => {
    // Previously hidden: 03:00 fell outside a 9-to-5 grid. The grid now covers
    // midnight to midnight, so there is no hour the line can fall off.
    const { container } = draw({}, { now: new Date('2026-08-11T03:00:00Z') })
    const line = container.querySelector('.now-line') as HTMLElement

    expect(line).not.toBeNull()
    // 03:00 = 180 minutes, at 0.9px per minute, measured from midnight.
    expect(line.style.top).toBe('162px')
  })
})

// --- Scrolling through the whole day ------------------------------------

describe('the full-day grid', () => {
  it('draws every hour from midnight to midnight', () => {
    const { container } = draw()
    const gutter = container.querySelector('.week-hours')!

    // 25 labels: one per hour boundary, midnight at both ends.
    expect(gutter.querySelectorAll('.week-hour')).toHaveLength(25)
  })

  it('is a full 24 hours tall regardless of the working day', () => {
    const { container } = draw({
      preferences: { ...schedule().preferences, day_start: '10:00:00', day_end: '14:00:00' },
    })
    const body = container.querySelector('.week-body') as HTMLElement

    // 1440 minutes x 0.9px. A 10-to-2 working day must not shrink the grid.
    expect(body.style.height).toBe('1296px')
  })

  it('puts a block at its true offset from midnight', () => {
    // Not relative to the working day: 09:00 is 540 minutes in, so 486px.
    const { container } = draw({ events: [event()] })
    const block = container.querySelector('.block.kind-imported') as HTMLElement

    expect(block.style.top).toBe('486px')
  })

  it('scrolls the body rather than clipping it', () => {
    const { container } = draw()

    expect(container.querySelector('.week-scroll')).not.toBeNull()
  })

  it('keeps the day headings frozen inside the scrolling box', () => {
    // Both live in the same scroll container on purpose: a scrollbar that
    // narrowed the body but not the header would drift every column out of
    // line with its date.
    const { container } = draw()
    const scroll = container.querySelector('.week-scroll')!

    expect(scroll.querySelector('.week-frozen .week-head')).not.toBeNull()
    expect(scroll.querySelector('.week-body')).not.toBeNull()
  })
})

describe('where the view opens', () => {
  it('opens on the start of the working day, not on midnight', () => {
    const { container } = draw()
    const scroll = container.querySelector('.week-scroll') as HTMLElement

    // 09:00 = 540 minutes x 0.9px.
    expect(scroll.scrollTop).toBe(486)
  })

  it('follows the working day when the user changes it', () => {
    const { container } = draw({
      preferences: { ...schedule().preferences, day_start: '06:00:00' },
    })
    const scroll = container.querySelector('.week-scroll') as HTMLElement

    expect(scroll.scrollTop).toBe(6 * 60 * 0.9)
  })

  it('opens earlier when something is scheduled before those hours', () => {
    const { container } = draw({
      events: [
        event({
          availability: 'work_window',
          title: 'Early shift',
          starts_at: '2026-08-10T05:00:00Z',
          ends_at: '2026-08-10T09:00:00Z',
        }),
      ],
    })
    const scroll = container.querySelector('.week-scroll') as HTMLElement

    expect(scroll.scrollTop).toBe(5 * 60 * 0.9)
  })
})
