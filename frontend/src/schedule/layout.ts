/** Turns schedule data into positioned blocks for one day column.
 *
 * Pure functions only — no React, no DOM — so the overlap logic stays easy to
 * reason about and to test (#16). */

import type { BlockKind, ScheduleEvent, SchedulePeriod } from './types'
import { addDays, minutesSinceMidnight, toZoneClock } from './week'

/** An API timestamp as a zone-clock Date, ready for local date arithmetic.
 *
 * Every instant entering this module goes through here, so the positioning
 * below can stay plain and still render the user's timezone. */
function zoned(iso: string, timeZone: string): Date {
  return toZoneClock(new Date(iso), timeZone)
}

/** Very short blocks still need to be readable and clickable. */
export const MIN_BLOCK_MINUTES = 24

export type Block = {
  key: string
  kind: BlockKind
  title: string
  subtitle: string
  /** Minutes from midnight, clamped to the day being rendered. */
  startMin: number
  endMin: number
  /** Column position among mutually-overlapping blocks. */
  lane: number
  laneCount: number
  /** Periods only: settled inside the horizon, so it will not be moved. */
  locked?: boolean
  /** The event this block came from, for opening its detail. On a period this
   *  is the deadline it was generated to serve, not the block itself. */
  eventId?: number
  /** Set on generated blocks, which the user can delete. Its presence is what
   *  distinguishes a period from an event of the same shape. */
  periodId?: number
}

export type DeadlineMarker = {
  key: string
  title: string
  atMin: number
  source: 'imported' | 'manual'
  eventId: number
}

/** A span of the day the user is available to work in.
 *
 * Rendered as a background rather than a block: periods sit *inside* it, so it
 * must not take a lane or compete for width. */
export type WorkWindow = {
  key: string
  title: string
  startMin: number
  endMin: number
  eventId: number
}

type Placed = { startMin: number; endMin: number }

/** Assigns side-by-side lanes to overlapping blocks.
 *
 * Blocks are grouped into clusters of transitively-overlapping items, and lane
 * count is computed per cluster — so two overlapping events at 9am don't make
 * an unrelated 4pm event render at half width. */
export function assignLanes<T extends Placed>(items: T[]): (T & { lane: number; laneCount: number })[] {
  const sorted = [...items].sort(
    (a, b) => a.startMin - b.startMin || a.endMin - b.endMin,
  )

  const result: (T & { lane: number; laneCount: number })[] = []
  let cluster: (T & { lane: number })[] = []
  let clusterEnd = -Infinity

  const flushCluster = () => {
    const laneCount = cluster.reduce((max, item) => Math.max(max, item.lane + 1), 0)
    for (const item of cluster) result.push({ ...item, laneCount })
    cluster = []
  }

  for (const item of sorted) {
    if (item.startMin >= clusterEnd) {
      flushCluster()
      clusterEnd = -Infinity
    }
    // Reuse the lowest lane not occupied at this instant.
    const busy = new Set(
      cluster.filter((placed) => placed.endMin > item.startMin).map((p) => p.lane),
    )
    let lane = 0
    while (busy.has(lane)) lane += 1

    cluster.push({ ...item, lane })
    clusterEnd = Math.max(clusterEnd, item.endMin)
  }
  flushCluster()

  return result
}

/** Clamps an interval to the given day, or returns null if it misses entirely. */
function clampToDay(start: Date, end: Date, day: Date): Placed | null {
  const dayStart = new Date(day)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = addDays(dayStart, 1)

  if (end <= dayStart || start >= dayEnd) return null

  return {
    startMin: start < dayStart ? 0 : minutesSinceMidnight(start),
    // An event ending exactly at midnight belongs to this day, not the next.
    endMin: end >= dayEnd ? 24 * 60 : minutesSinceMidnight(end),
  }
}

export function buildDayBlocks(
  events: ScheduleEvent[],
  periods: SchedulePeriod[],
  day: Date,
  timeZone: string,
): Block[] {
  const raw: (Placed & Omit<Block, 'lane' | 'laneCount'>)[] = []

  for (const event of events) {
    // Deadlines are moments, not spans; all-day events sit in their own strip.
    if (event.event_type !== 'one_time' || event.is_all_day) continue
    // Work windows are backgrounds, not blocks — see buildWorkWindows.
    if (event.availability === 'work_window') continue
    if (!event.starts_at || !event.ends_at) continue

    const span = clampToDay(zoned(event.starts_at, timeZone),
                            zoned(event.ends_at, timeZone), day)
    if (!span) continue

    raw.push({
      ...span,
      key: `event-${event.id}`,
      kind: event.source,
      title: event.title,
      subtitle: event.source === 'imported' ? 'From calendar' : 'Added by you',
      eventId: event.id,
    })
  }

  for (const period of periods) {
    const span = clampToDay(zoned(period.starts_at, timeZone),
                            zoned(period.ends_at, timeZone), day)
    if (!span) continue

    if (period.kind === 'meal') {
      raw.push({
        ...span,
        key: `period-${period.id}`,
        kind: 'meal',
        title: 'Meal break',
        subtitle: 'Kept clear',
        locked: period.locked,
        periodId: period.id,
      })
      continue
    }

    raw.push({
      ...span,
      key: `period-${period.id}`,
      kind: 'period',
      title: period.events.map((e) => e.title).join(', ') || 'Work period',
      subtitle: period.locked ? 'Settled' : 'Work period',
      locked: period.locked,
      // Opens the deadline this block was generated to serve — settled or
      // not, the user still needs to see what they are working toward.
      eventId: period.events[0]?.id,
      periodId: period.id,
    })
  }

  // Lane math uses the *rendered* height so a padded-up short block does not
  // silently overlap its neighbour.
  const withVisualHeight = raw.map((block) => ({
    ...block,
    endMin: Math.max(block.endMin, block.startMin + MIN_BLOCK_MINUTES),
  }))

  return assignLanes(withVisualHeight)
}

export function buildDeadlineMarkers(
  events: ScheduleEvent[],
  day: Date,
  timeZone: string,
): DeadlineMarker[] {
  const dayStart = new Date(day)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = addDays(dayStart, 1)

  return events
    .filter((event): event is ScheduleEvent & { due_at: string } => {
      if (event.event_type !== 'deadline' || !event.due_at) return false
      const due = zoned(event.due_at, timeZone)
      return due >= dayStart && due < dayEnd
    })
    .map((event) => ({
      key: `deadline-${event.id}`,
      title: event.title,
      atMin: minutesSinceMidnight(zoned(event.due_at, timeZone)),
      source: event.source as 'imported' | 'manual',
      eventId: event.id,
    }))
    .sort((a, b) => a.atMin - b.atMin)
}

/** Spans of the day the user is available to work in, clamped to `day`. */
export function buildWorkWindows(
  events: ScheduleEvent[],
  day: Date,
  timeZone: string,
): WorkWindow[] {
  const windows: WorkWindow[] = []

  for (const event of events) {
    if (event.availability !== 'work_window') continue
    if (!event.starts_at || !event.ends_at) continue

    const span = clampToDay(zoned(event.starts_at, timeZone),
                            zoned(event.ends_at, timeZone), day)
    if (!span) continue

    windows.push({
      ...span,
      key: `window-${event.id}`,
      title: event.title,
      eventId: event.id,
    })
  }

  return windows.sort((a, b) => a.startMin - b.startMin)
}

export function allDayEvents(
  events: ScheduleEvent[],
  day: Date,
  timeZone: string,
): ScheduleEvent[] {
  const dayStart = new Date(day)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = addDays(dayStart, 1)

  return events.filter((event) => {
    if (!event.is_all_day || !event.starts_at || !event.ends_at) return false
    return (
      zoned(event.starts_at, timeZone) < dayEnd &&
      zoned(event.ends_at, timeZone) > dayStart
    )
  })
}

/** Vertical bounds of the grid: the user's working hours, widened to fit
 * anything scheduled outside them so nothing is ever clipped. */
export function gridBounds(
  blocks: Block[][],
  markers: DeadlineMarker[][],
  preferredStart: number,
  preferredEnd: number,
  windows: WorkWindow[][] = [],
): { startMin: number; endMin: number } {
  let startMin = preferredStart
  let endMin = preferredEnd

  for (const day of blocks) {
    for (const block of day) {
      startMin = Math.min(startMin, block.startMin)
      endMin = Math.max(endMin, block.endMin)
    }
  }
  // A shift starting before the user's usual hours must not be clipped.
  for (const day of windows) {
    for (const window of day) {
      startMin = Math.min(startMin, window.startMin)
      endMin = Math.max(endMin, window.endMin)
    }
  }
  for (const day of markers) {
    for (const marker of day) {
      startMin = Math.min(startMin, marker.atMin)
      endMin = Math.max(endMin, marker.atMin + MIN_BLOCK_MINUTES)
    }
  }

  // Snap outward to whole hours so the gutter labels line up.
  return {
    startMin: Math.floor(startMin / 60) * 60,
    endMin: Math.min(24 * 60, Math.ceil(endMin / 60) * 60),
  }
}
