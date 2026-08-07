/** Turns schedule data into positioned blocks for one day column.
 *
 * Pure functions only — no React, no DOM — so the overlap logic stays easy to
 * reason about and to test (#16). */

import type { BlockKind, ScheduleEvent, SchedulePeriod } from './types'
import { addDays, minutesSinceMidnight } from './week'

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
}

export type DeadlineMarker = {
  key: string
  title: string
  atMin: number
  source: 'imported' | 'manual'
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
): Block[] {
  const raw: (Placed & Omit<Block, 'lane' | 'laneCount'>)[] = []

  for (const event of events) {
    // Deadlines are moments, not spans; all-day events sit in their own strip.
    if (event.event_type !== 'one_time' || event.is_all_day) continue
    if (!event.starts_at || !event.ends_at) continue

    const span = clampToDay(new Date(event.starts_at), new Date(event.ends_at), day)
    if (!span) continue

    raw.push({
      ...span,
      key: `event-${event.id}`,
      kind: event.source,
      title: event.title,
      subtitle: event.source === 'imported' ? 'From calendar' : 'Added by you',
    })
  }

  for (const period of periods) {
    const span = clampToDay(new Date(period.starts_at), new Date(period.ends_at), day)
    if (!span) continue

    raw.push({
      ...span,
      key: `period-${period.id}`,
      kind: 'period',
      title: period.events.map((e) => e.title).join(', ') || 'Work period',
      subtitle: period.locked ? 'Settled' : 'Work period',
      locked: period.locked,
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
): DeadlineMarker[] {
  const dayStart = new Date(day)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = addDays(dayStart, 1)

  return events
    .filter((event): event is ScheduleEvent & { due_at: string } => {
      if (event.event_type !== 'deadline' || !event.due_at) return false
      const due = new Date(event.due_at)
      return due >= dayStart && due < dayEnd
    })
    .map((event) => ({
      key: `deadline-${event.id}`,
      title: event.title,
      atMin: minutesSinceMidnight(new Date(event.due_at)),
      source: event.source as 'imported' | 'manual',
    }))
    .sort((a, b) => a.atMin - b.atMin)
}

export function allDayEvents(events: ScheduleEvent[], day: Date): ScheduleEvent[] {
  const dayStart = new Date(day)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = addDays(dayStart, 1)

  return events.filter((event) => {
    if (!event.is_all_day || !event.starts_at || !event.ends_at) return false
    return new Date(event.starts_at) < dayEnd && new Date(event.ends_at) > dayStart
  })
}

/** Vertical bounds of the grid: the user's working hours, widened to fit
 * anything scheduled outside them so nothing is ever clipped. */
export function gridBounds(
  blocks: Block[][],
  markers: DeadlineMarker[][],
  preferredStart: number,
  preferredEnd: number,
): { startMin: number; endMin: number } {
  let startMin = preferredStart
  let endMin = preferredEnd

  for (const day of blocks) {
    for (const block of day) {
      startMin = Math.min(startMin, block.startMin)
      endMin = Math.max(endMin, block.endMin)
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
