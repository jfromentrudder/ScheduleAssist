/** Turns schedule data into month-grid cells.
 *
 * Pure functions only, like `layout.ts`, so what belongs in a cell can be
 * reasoned about without rendering one.
 *
 * A month answers a different question from a week — "what is coming up", not
 * "what am I doing at two o'clock" — and that changes what earns space. Events
 * are what the user recognises, so they get chips. Generated periods are the
 * app's own output and there can be a dozen a day: as chips they would bury the
 * commitments the month exists to show, so they collapse to a single count.
 */

import type { ScheduleEvent, SchedulePeriod } from './types'
import { addDays, minutesSinceMidnight, toZoneClock } from './week'

/** How many chips fit a cell before the rest become "+N more". */
export const MAX_CHIPS_PER_CELL = 3

export type MonthChip = {
  key: string
  /** `deadline` takes the due colour; the others follow the event's source. */
  kind: 'deadline' | 'imported' | 'manual'
  title: string
  /** Start time for a timed event, "All day" otherwise, "Due" for a deadline. */
  when: string
  eventId: number
  /** Minutes from midnight, for ordering. Deadlines sort by their due time. */
  atMin: number
}

export type MonthCell = {
  key: string
  day: Date
  /** False for the leading and trailing days borrowed from adjacent months. */
  inMonth: boolean
  chips: MonthChip[]
  /** Chips that did not fit. Zero when everything is shown. */
  hiddenCount: number
  /** Generated work periods on this day. Meals are excluded — they are not
   *  work, and counting them would overstate the day's load. */
  periodCount: number
  periodMinutes: number
}

function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

/** Does an interval touch the day at all, however briefly? */
function overlapsDay(start: Date, end: Date, day: Date): boolean {
  const dayStart = new Date(day)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = addDays(dayStart, 1)
  return start < dayEnd && end > dayStart
}

function formatWhen(date: Date): string {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function chipsForDay(
  events: ScheduleEvent[],
  day: Date,
  timeZone: string,
): MonthChip[] {
  const chips: MonthChip[] = []

  for (const event of events) {
    if (event.event_type === 'deadline') {
      if (!event.due_at) continue
      const due = toZoneClock(new Date(event.due_at), timeZone)
      if (!sameDay(due, day)) continue
      chips.push({
        key: `deadline-${event.id}`,
        kind: 'deadline',
        title: event.title,
        when: `Due ${formatWhen(due)}`,
        eventId: event.id,
        atMin: minutesSinceMidnight(due),
      })
      continue
    }

    if (!event.starts_at || !event.ends_at) continue
    const start = toZoneClock(new Date(event.starts_at), timeZone)
    const end = toZoneClock(new Date(event.ends_at), timeZone)
    if (!overlapsDay(start, end, day)) continue

    chips.push({
      key: `event-${event.id}`,
      kind: event.source,
      title: event.title,
      // An all-day entry, or one continuing from an earlier day, has no start
      // time worth showing against this cell.
      when: event.is_all_day || !sameDay(start, day) ? 'All day' : formatWhen(start),
      eventId: event.id,
      atMin: event.is_all_day || !sameDay(start, day) ? -1 : minutesSinceMidnight(start),
    })
  }

  // All-day first, then by time; ties broken by title so the order is stable.
  return chips.sort((a, b) => a.atMin - b.atMin || a.title.localeCompare(b.title))
}

export function monthCells(
  events: ScheduleEvent[],
  periods: SchedulePeriod[],
  days: Date[],
  timeZone: string,
  /** Which month the grid is *of*; the rest of its days are dimmed. Taken from
   *  a day known to be inside it rather than from the grid's first cell, which
   *  usually belongs to the month before. */
  monthOf: Date,
): MonthCell[] {
  return days.map((day) => {
    const onThisDay = periods.filter((period) => {
      if (period.kind !== 'work') return false
      return sameDay(toZoneClock(new Date(period.starts_at), timeZone), day)
    })

    const minutes = onThisDay.reduce((total, period) => {
      const start = new Date(period.starts_at).getTime()
      const end = new Date(period.ends_at).getTime()
      return total + Math.round((end - start) / 60_000)
    }, 0)

    const all = chipsForDay(events, day, timeZone)

    return {
      key: day.toISOString(),
      day,
      inMonth: day.getMonth() === monthOf.getMonth() &&
        day.getFullYear() === monthOf.getFullYear(),
      chips: all.slice(0, MAX_CHIPS_PER_CELL),
      hiddenCount: Math.max(0, all.length - MAX_CHIPS_PER_CELL),
      periodCount: onThisDay.length,
      periodMinutes: minutes,
    }
  })
}

/** "4 periods · 3h 20m", or null when the day has none. */
export function formatPeriodLoad(count: number, minutes: number): string | null {
  if (count === 0) return null
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  const duration = hours > 0
    ? remainder > 0 ? `${hours}h ${remainder}m` : `${hours}h`
    : `${remainder}m`
  return `${count} ${count === 1 ? 'period' : 'periods'} · ${duration}`
}
