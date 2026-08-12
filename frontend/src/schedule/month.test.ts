/** Tests for what belongs in a month cell.
 *
 * The load-bearing rule: events become chips, generated periods become a count.
 * Getting that backwards would fill a month with the app's own output and bury
 * the commitments the view exists to surface. */

import { describe, expect, it } from 'vitest'

import { MAX_CHIPS_PER_CELL, formatPeriodLoad, monthCells } from './month'
import type { ScheduleEvent, SchedulePeriod } from './types'

const UTC = 'UTC'
/** Mon 10 Aug 2026 through Wed 12th, as zone-clock dates. */
const DAYS = [
  new Date(2026, 7, 10, 12),
  new Date(2026, 7, 11, 12),
  new Date(2026, 7, 12, 12),
]
const AUGUST = new Date(2026, 7, 15)

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

const cellsFor = (events: ScheduleEvent[], periods: SchedulePeriod[] = []) =>
  monthCells(events, periods, DAYS, UTC, AUGUST)

// --- Which month a cell belongs to --------------------------------------

describe('the month a cell belongs to', () => {
  it('marks days inside the month', () => {
    expect(cellsFor([]).every((c) => c.inMonth)).toBe(true)
  })

  it('marks the leading days borrowed from the month before', () => {
    // The grid for August 2026 opens on Monday 27 July.
    const july = [new Date(2026, 6, 27, 12), new Date(2026, 7, 1, 12)]
    const cells = monthCells([], [], july, UTC, AUGUST)

    expect(cells.map((c) => c.inMonth)).toEqual([false, true])
  })

  it('does not confuse the same month in a different year', () => {
    const cells = monthCells([], [], [new Date(2025, 7, 12, 12)], UTC, AUGUST)

    expect(cells[0].inMonth).toBe(false)
  })
})

// --- Chips --------------------------------------------------------------

describe('event chips', () => {
  it('places a timed event on its day, with its start time', () => {
    const [monday] = cellsFor([event()])

    expect(monday.chips).toHaveLength(1)
    expect(monday.chips[0].title).toBe('Standup')
    expect(monday.chips[0].kind).toBe('imported')
    expect(monday.chips[0].when).toMatch(/9:00/)
  })

  it('distinguishes an event the user added themselves', () => {
    const [monday] = cellsFor([event({ source: 'manual' })])

    expect(monday.chips[0].kind).toBe('manual')
  })

  it('gives a deadline its own kind and its due time', () => {
    const [, , wednesday] = cellsFor([
      event({
        event_type: 'deadline',
        starts_at: null,
        ends_at: null,
        due_at: '2026-08-12T17:00:00Z',
      }),
    ])

    expect(wednesday.chips[0].kind).toBe('deadline')
    expect(wednesday.chips[0].when).toMatch(/^Due /)
  })

  it('labels an all-day event rather than inventing a time', () => {
    const [monday] = cellsFor([
      event({
        is_all_day: true,
        starts_at: '2026-08-10T00:00:00Z',
        ends_at: '2026-08-11T00:00:00Z',
      }),
    ])

    expect(monday.chips[0].when).toBe('All day')
  })

  it('appears on every day a multi-day event covers', () => {
    const cells = cellsFor([
      event({
        title: 'Conference',
        starts_at: '2026-08-10T09:00:00Z',
        ends_at: '2026-08-12T17:00:00Z',
      }),
    ])

    expect(cells.map((c) => c.chips.length)).toEqual([1, 1, 1])
    // Only the first day shows a start time; the others are continuations.
    expect(cells[1].chips[0].when).toBe('All day')
  })

  it('sorts all-day entries above timed ones, then by time', () => {
    const cells = cellsFor([
      event({ id: 1, title: 'Late', starts_at: '2026-08-10T16:00:00Z', ends_at: '2026-08-10T17:00:00Z' }),
      event({ id: 2, title: 'Early', starts_at: '2026-08-10T09:00:00Z', ends_at: '2026-08-10T10:00:00Z' }),
      event({
        id: 3,
        title: 'Holiday',
        is_all_day: true,
        starts_at: '2026-08-10T00:00:00Z',
        ends_at: '2026-08-11T00:00:00Z',
      }),
    ])

    expect(cells[0].chips.map((c) => c.title)).toEqual(['Holiday', 'Early', 'Late'])
  })

  it('leaves a day with nothing on it empty', () => {
    const cells = cellsFor([event()])

    expect(cells[1].chips).toHaveLength(0)
    expect(cells[1].hiddenCount).toBe(0)
  })
})

describe('when a cell overflows', () => {
  const at = (hour: number) =>
    `2026-08-10T${String(hour).padStart(2, '0')}:00:00Z`

  const many = Array.from({ length: 6 }, (_, i) =>
    event({
      id: i + 1,
      title: `Thing ${i + 1}`,
      starts_at: at(i + 4),
      ends_at: at(i + 5),
    }),
  )

  it('shows only as many chips as fit', () => {
    const [monday] = cellsFor(many)

    expect(monday.chips).toHaveLength(MAX_CHIPS_PER_CELL)
  })

  it('counts the rest', () => {
    const [monday] = cellsFor(many)

    expect(monday.hiddenCount).toBe(6 - MAX_CHIPS_PER_CELL)
  })

  it('keeps the earliest, since those are the ones coming first', () => {
    const [monday] = cellsFor(many)

    expect(monday.chips.map((c) => c.title)).toEqual(['Thing 1', 'Thing 2', 'Thing 3'])
  })
})

// --- Periods, as a count ------------------------------------------------

describe('generated periods', () => {
  it('are counted rather than turned into chips', () => {
    const [monday] = cellsFor([], [period()])

    expect(monday.periodCount).toBe(1)
    expect(monday.chips).toHaveLength(0)
  })

  it('total their minutes', () => {
    const [monday] = cellsFor([], [
      period({ id: 1 }),
      period({ id: 2, starts_at: '2026-08-10T15:00:00Z', ends_at: '2026-08-10T16:00:00Z' }),
    ])

    expect(monday.periodCount).toBe(2)
    expect(monday.periodMinutes).toBe(50 + 60)
  })

  it('are counted on their own day only', () => {
    const cells = cellsFor([], [period()])

    expect(cells.map((c) => c.periodCount)).toEqual([1, 0, 0])
  })

  it('exclude meal breaks, which are not work', () => {
    const [monday] = cellsFor([], [
      period({ id: 1 }),
      period({ id: 2, kind: 'meal', events: [] }),
    ])

    expect(monday.periodCount).toBe(1)
  })
})

describe('formatPeriodLoad', () => {
  it('says nothing when the day has no periods', () => {
    expect(formatPeriodLoad(0, 0)).toBeNull()
  })

  it('reads as a count and a duration', () => {
    expect(formatPeriodLoad(4, 200)).toBe('4 periods · 3h 20m')
  })

  it('drops the minutes when the total is whole hours', () => {
    expect(formatPeriodLoad(3, 180)).toBe('3 periods · 3h')
  })

  it('shows minutes alone under an hour', () => {
    expect(formatPeriodLoad(1, 50)).toBe('1 period · 50m')
  })
})
