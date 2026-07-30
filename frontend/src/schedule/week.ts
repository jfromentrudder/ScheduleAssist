/** Date helpers for the week grid. All times render in the browser's local
 * zone; see the note in Schedule.tsx about the user's configured timezone. */

export const DAYS_IN_WEEK = 7

/** Monday of the week containing `date`, at local midnight. */
export function startOfWeek(date: Date): Date {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  // getDay() is Sunday-based; the app treats Monday as day 0 throughout.
  const mondayOffset = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - mondayOffset)
  return d
}

export function addDays(date: Date, days: number): Date {
  const d = new Date(date)
  d.setDate(d.getDate() + days)
  return d
}

export function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export function minutesSinceMidnight(date: Date): number {
  return date.getHours() * 60 + date.getMinutes()
}

/** Parses the "HH:MM:SS" the API returns for day_start / day_end. */
export function parseClockTime(value: string): number {
  const [hours, minutes] = value.split(':').map(Number)
  return hours * 60 + (minutes || 0)
}

export function formatHour(minutes: number): string {
  const date = new Date()
  date.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0)
  return date.toLocaleTimeString([], { hour: 'numeric' })
}

export function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

/** "Jul 27 – Aug 2, 2026", collapsing the month when both ends share it. */
export function formatWeekRange(weekStart: Date): string {
  const weekEnd = addDays(weekStart, DAYS_IN_WEEK - 1)
  const sameMonth = weekStart.getMonth() === weekEnd.getMonth()
  const startLabel = weekStart.toLocaleDateString([], { month: 'short', day: 'numeric' })
  const endLabel = weekEnd.toLocaleDateString(
    [],
    sameMonth ? { day: 'numeric' } : { month: 'short', day: 'numeric' },
  )
  return `${startLabel} – ${endLabel}, ${weekEnd.getFullYear()}`
}
