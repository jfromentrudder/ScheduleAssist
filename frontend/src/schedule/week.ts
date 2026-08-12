/** Date helpers for the week grid.
 *
 * The grid renders in the *user's* configured timezone, which is not
 * necessarily the browser's. Rather than thread a zone through every piece of
 * date arithmetic, instants are converted once at the edge into a "zone clock"
 * Date — see `toZoneClock` — after which ordinary local date methods position
 * blocks correctly. */

export const DAYS_IN_WEEK = 7

/** Milliseconds to add to an instant to read its wall clock in `timeZone`. */
function zoneOffset(date: Date, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(date)

  const get = (type: string) => Number(parts.find((p) => p.type === type)!.value)
  const asUTC = Date.UTC(
    get('year'),
    get('month') - 1,
    get('day'),
    // Some engines render midnight as hour 24 under hour12: false.
    get('hour') % 24,
    get('minute'),
    get('second'),
  )
  return asUTC - date.getTime()
}

/** A Date whose *browser-local* clock reads what `date` reads in `timeZone`.
 *
 * Not a real instant, and must never be sent to the server or compared with
 * one. It exists so the grid can keep using getHours/setDate while displaying
 * a zone the browser is not in. */
export function toZoneClock(date: Date, timeZone: string): Date {
  const wall = date.getTime() + zoneOffset(date, timeZone)
  // getTimezoneOffset depends on the date it is read from, so settle it in two
  // passes; the second is what gets a DST boundary right.
  let shifted = new Date(wall + new Date(wall).getTimezoneOffset() * 60_000)
  shifted = new Date(wall + shifted.getTimezoneOffset() * 60_000)
  return shifted
}

/** The real instant behind a zone-clock Date. The inverse of `toZoneClock`. */
export function fromZoneClock(local: Date, timeZone: string): Date {
  const wall = Date.UTC(
    local.getFullYear(),
    local.getMonth(),
    local.getDate(),
    local.getHours(),
    local.getMinutes(),
    local.getSeconds(),
  )
  let instant = new Date(wall - zoneOffset(new Date(wall), timeZone))
  instant = new Date(wall - zoneOffset(instant, timeZone))
  return instant
}

/** Monday of the week containing `date`, as the instant it begins in `timeZone`. */
export function startOfWeekIn(date: Date, timeZone: string): Date {
  const local = toZoneClock(date, timeZone)
  local.setHours(0, 0, 0, 0)
  // getDay() is Sunday-based; the app treats Monday as day 0 throughout.
  local.setDate(local.getDate() - ((local.getDay() + 6) % 7))
  return fromZoneClock(local, timeZone)
}

/** `weeks` later than `instant`, counted in `timeZone`.
 *
 * Adding 7×24h would drift an hour across a DST boundary; stepping the date in
 * the zone's own calendar does not. */
export function addWeeksIn(
  instant: Date,
  weeks: number,
  timeZone: string,
): Date {
  const local = toZoneClock(instant, timeZone)
  local.setDate(local.getDate() + weeks * DAYS_IN_WEEK)
  return fromZoneClock(local, timeZone)
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
