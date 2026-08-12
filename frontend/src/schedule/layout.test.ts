/** Tests for the block-positioning maths.
 *
 * These are the functions the week grid is built on, and the ones whose bugs
 * are invisible in a screenshot: a block half a lane too wide, or a period that
 * silently vanishes because it started on the previous day. */

import { describe, expect, it } from 'vitest'

import {
  MIN_BLOCK_MINUTES,
  MINUTES_IN_DAY,
  allDayEvents,
  assignLanes,
  buildDayBlocks,
  buildDeadlineMarkers,
  buildWorkWindows,
  openingMinute,
} from './layout'
import type { ScheduleEvent, SchedulePeriod } from './types'

const UTC = 'UTC'
/** The day every fixture below sits on, as a zone-clock Date. */
const DAY = new Date(2026, 7, 10, 12, 0, 0) // Mon 10 Aug 2026, local noon

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

// --- Lanes --------------------------------------------------------------

describe('assignLanes', () => {
  it('gives a single block the full width', () => {
    const [only] = assignLanes([{ startMin: 540, endMin: 600 }])

    expect(only.lane).toBe(0)
    expect(only.laneCount).toBe(1)
  })

  it('splits two overlapping blocks into side-by-side lanes', () => {
    const placed = assignLanes([
      { startMin: 540, endMin: 660 },
      { startMin: 600, endMin: 720 },
    ])

    expect(placed.map((p) => p.lane)).toEqual([0, 1])
    expect(placed.every((p) => p.laneCount === 2)).toBe(true)
  })

  it('counts lanes per cluster, so an unrelated block stays full width', () => {
    // The bug this guards: computing laneCount across the whole day would
    // render the 4pm block at half width because of a 9am collision.
    const placed = assignLanes([
      { startMin: 540, endMin: 660 }, // 9:00-11:00  ┐ overlap
      { startMin: 600, endMin: 720 }, // 10:00-12:00 ┘
      { startMin: 960, endMin: 1020 }, // 16:00-17:00, alone
    ])

    const alone = placed.find((p) => p.startMin === 960)!
    expect(alone.laneCount).toBe(1)
    expect(placed.filter((p) => p.laneCount === 2)).toHaveLength(2)
  })

  it('reuses a lane once the block occupying it has ended', () => {
    const placed = assignLanes([
      { startMin: 540, endMin: 600 },
      { startMin: 550, endMin: 610 }, // overlaps the first, takes lane 1
      { startMin: 605, endMin: 665 }, // first has ended, so lane 0 is free
    ])

    expect(placed.map((p) => p.lane)).toEqual([0, 1, 0])
  })

  it('treats blocks that merely touch as not overlapping', () => {
    const placed = assignLanes([
      { startMin: 540, endMin: 600 },
      { startMin: 600, endMin: 660 },
    ])

    expect(placed.every((p) => p.laneCount === 1)).toBe(true)
  })
})

// --- Blocks -------------------------------------------------------------

describe('buildDayBlocks', () => {
  it('carries the period id, so the block can be deleted', () => {
    const [block] = buildDayBlocks([], [period()], DAY, UTC)

    expect(block.periodId).toBe(10)
    expect(block.kind).toBe('period')
  })

  it('labels a period with the deadlines it serves', () => {
    const [block] = buildDayBlocks([], [period()], DAY, UTC)

    expect(block.title).toBe('Essay')
    // Opens the deadline it was generated for, not the period itself.
    expect(block.eventId).toBe(1)
  })

  it('falls back to a generic label when the deadline is another week', () => {
    const [block] = buildDayBlocks([], [period({ events: [] })], DAY, UTC)

    expect(block.title).toBe('Work period')
    expect(block.eventId).toBeUndefined()
  })

  it('marks a settled period as locked and says so', () => {
    const [block] = buildDayBlocks([], [period({ locked: true })], DAY, UTC)

    expect(block.locked).toBe(true)
    expect(block.subtitle).toBe('Settled')
  })

  it('renders a meal break as its own kind, still deletable', () => {
    const [block] = buildDayBlocks(
      [],
      [period({ kind: 'meal', events: [] })],
      DAY,
      UTC,
    )

    expect(block.kind).toBe('meal')
    expect(block.title).toBe('Meal break')
    expect(block.periodId).toBe(10)
  })

  it('keeps events and periods apart by kind', () => {
    const blocks = buildDayBlocks([event()], [period()], DAY, UTC)

    expect(blocks.map((b) => b.kind).sort()).toEqual(['imported', 'period'])
  })

  it('leaves out deadlines, which are moments rather than spans', () => {
    const deadline = event({
      event_type: 'deadline',
      starts_at: null,
      ends_at: null,
      due_at: '2026-08-10T17:00:00Z',
    })

    expect(buildDayBlocks([deadline], [], DAY, UTC)).toHaveLength(0)
  })

  it('leaves out all-day events, which sit in their own strip', () => {
    expect(buildDayBlocks([event({ is_all_day: true })], [], DAY, UTC)).toHaveLength(0)
  })

  it('leaves out work windows, which render as a background', () => {
    const shift = event({ availability: 'work_window' })

    expect(buildDayBlocks([shift], [], DAY, UTC)).toHaveLength(0)
  })

  it('clamps a block that started the day before', () => {
    const overnight = event({
      starts_at: '2026-08-09T22:00:00Z',
      ends_at: '2026-08-10T02:00:00Z',
    })

    const [block] = buildDayBlocks([overnight], [], DAY, UTC)

    expect(block.startMin).toBe(0)
    expect(block.endMin).toBe(120)
  })

  it('clamps a block that runs into the next day', () => {
    const overnight = event({
      starts_at: '2026-08-10T22:00:00Z',
      ends_at: '2026-08-11T02:00:00Z',
    })

    const [block] = buildDayBlocks([overnight], [], DAY, UTC)

    expect(block.startMin).toBe(22 * 60)
    expect(block.endMin).toBe(24 * 60)
  })

  it('gives an event ending exactly at midnight to the day it started', () => {
    const untilMidnight = event({
      starts_at: '2026-08-10T23:00:00Z',
      ends_at: '2026-08-11T00:00:00Z',
    })

    expect(buildDayBlocks([untilMidnight], [], DAY, UTC)).toHaveLength(1)
    const tomorrow = new Date(2026, 7, 11, 12)
    expect(buildDayBlocks([untilMidnight], [], tomorrow, UTC)).toHaveLength(0)
  })

  it('drops anything on another day entirely', () => {
    const nextWeek = event({
      starts_at: '2026-08-17T09:00:00Z',
      ends_at: '2026-08-17T10:00:00Z',
    })

    expect(buildDayBlocks([nextWeek], [], DAY, UTC)).toHaveLength(0)
  })

  it('pads a very short block to stay readable, and lanes it at that height', () => {
    const brief = event({
      starts_at: '2026-08-10T09:00:00Z',
      ends_at: '2026-08-10T09:05:00Z',
    })
    // Starts inside the padded height of the first, so they must not collide.
    const after = event({
      id: 2,
      starts_at: '2026-08-10T09:10:00Z',
      ends_at: '2026-08-10T09:40:00Z',
    })

    const blocks = buildDayBlocks([brief, after], [], DAY, UTC)
    const first = blocks.find((b) => b.eventId === 1)!

    expect(first.endMin - first.startMin).toBe(MIN_BLOCK_MINUTES)
    expect(blocks.every((b) => b.laneCount === 2)).toBe(true)
  })
})

// --- Deadlines, windows, all-day ---------------------------------------

describe('buildDeadlineMarkers', () => {
  it('places a deadline at its due minute', () => {
    const deadline = event({
      event_type: 'deadline',
      starts_at: null,
      ends_at: null,
      due_at: '2026-08-10T17:30:00Z',
      source: 'manual',
    })

    const [marker] = buildDeadlineMarkers([deadline], DAY, UTC)

    expect(marker.atMin).toBe(17 * 60 + 30)
    expect(marker.title).toBe('Standup')
    expect(marker.source).toBe('manual')
  })

  it('ignores deadlines due on another day', () => {
    const deadline = event({
      event_type: 'deadline',
      starts_at: null,
      ends_at: null,
      due_at: '2026-08-12T17:00:00Z',
    })

    expect(buildDeadlineMarkers([deadline], DAY, UTC)).toHaveLength(0)
  })

  it('returns them in time order', () => {
    const at = (id: number, iso: string) =>
      event({ id, event_type: 'deadline', starts_at: null, ends_at: null, due_at: iso })

    const markers = buildDeadlineMarkers(
      [at(1, '2026-08-10T17:00:00Z'), at(2, '2026-08-10T09:00:00Z')],
      DAY,
      UTC,
    )

    expect(markers.map((m) => m.eventId)).toEqual([2, 1])
  })
})

describe('buildWorkWindows', () => {
  it('returns a shift as a background span', () => {
    const shift = event({
      availability: 'work_window',
      title: 'At work',
      starts_at: '2026-08-10T08:00:00Z',
      ends_at: '2026-08-10T16:00:00Z',
    })

    const [window] = buildWorkWindows([shift], DAY, UTC)

    expect(window.startMin).toBe(8 * 60)
    expect(window.endMin).toBe(16 * 60)
    expect(window.title).toBe('At work')
  })

  it('ignores events that are not work windows', () => {
    expect(buildWorkWindows([event()], DAY, UTC)).toHaveLength(0)
  })
})

describe('allDayEvents', () => {
  it('picks up an all-day event overlapping the day', () => {
    const marker = event({
      is_all_day: true,
      title: 'Reading day',
      starts_at: '2026-08-10T00:00:00Z',
      ends_at: '2026-08-11T00:00:00Z',
    })

    expect(allDayEvents([marker], DAY, UTC).map((e) => e.title)).toEqual([
      'Reading day',
    ])
  })

  it('leaves timed events to the grid', () => {
    expect(allDayEvents([event()], DAY, UTC)).toHaveLength(0)
  })
})

// --- Where the view opens -----------------------------------------------
//
// The grid draws a whole day and scrolls, so this decides only what is above
// the fold. Nothing is ever clipped, which is why there is no upper bound to
// compute any more.

describe('openingMinute', () => {
  it('opens on the start of the working day', () => {
    expect(openingMinute([], [], 9 * 60)).toBe(9 * 60)
  })

  it('opens earlier when a block would otherwise be above the fold', () => {
    const early = buildDayBlocks(
      [event({ starts_at: '2026-08-10T06:30:00Z', ends_at: '2026-08-10T07:00:00Z' })],
      [],
      DAY,
      UTC,
    )

    // Snapped back to a whole hour so the view opens flush with a gutter label.
    expect(openingMinute([early], [], 9 * 60)).toBe(6 * 60)
  })

  it('opens earlier for a shift that starts before the working day', () => {
    const windows = buildWorkWindows(
      [
        event({
          availability: 'work_window',
          starts_at: '2026-08-10T05:00:00Z',
          ends_at: '2026-08-10T13:00:00Z',
        }),
      ],
      DAY,
      UTC,
    )

    // Every argument is per-day, so a single day's windows still nest.
    expect(openingMinute([], [], 9 * 60, [windows])).toBe(5 * 60)
  })

  it('opens earlier for a deadline due before the working day', () => {
    const markers = buildDeadlineMarkers(
      [
        event({
          event_type: 'deadline',
          starts_at: null,
          ends_at: null,
          due_at: '2026-08-10T02:30:00Z',
        }),
      ],
      DAY,
      UTC,
    )

    expect(openingMinute([], [markers], 9 * 60)).toBe(2 * 60)
  })

  it('ignores anything later than the working day, which is reachable by scrolling', () => {
    const late = buildDayBlocks(
      [event({ starts_at: '2026-08-10T22:00:00Z', ends_at: '2026-08-10T23:00:00Z' })],
      [],
      DAY,
      UTC,
    )

    expect(openingMinute([late], [], 9 * 60)).toBe(9 * 60)
  })

  it('never opens above midnight', () => {
    const atMidnight = buildDayBlocks(
      [event({ starts_at: '2026-08-10T00:00:00Z', ends_at: '2026-08-10T01:00:00Z' })],
      [],
      DAY,
      UTC,
    )

    expect(openingMinute([atMidnight], [], 9 * 60)).toBe(0)
  })

  it('draws a full day, so every minute is reachable', () => {
    expect(MINUTES_IN_DAY).toBe(1440)
  })
})
