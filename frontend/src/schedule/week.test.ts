/** Tests for the week grid's date arithmetic.
 *
 * The grid renders in the user's configured timezone, which is not the
 * browser's, and every one of these functions has a failure mode that only
 * appears when those two differ or when a DST boundary falls inside the week.
 * The suite pins the browser to America/Los_Angeles (see vite.config.ts) so
 * "the browser's zone" is a real, DST-observing zone rather than whatever the
 * machine happens to be set to. */

import { describe, expect, it } from 'vitest'

import {
  addDays,
  addWeeksIn,
  formatWeekRange,
  fromZoneClock,
  isSameDay,
  minutesSinceMidnight,
  parseClockTime,
  startOfWeekIn,
  toZoneClock,
} from './week'

const NY = 'America/New_York'
const TOKYO = 'Asia/Tokyo'
const UTC = 'UTC'

describe('toZoneClock', () => {
  it("reads an instant's wall clock in the target zone", () => {
    // 14:00 UTC is 10:00 in New York during daylight time.
    const clock = toZoneClock(new Date('2026-08-10T14:00:00Z'), NY)

    expect(clock.getHours()).toBe(10)
    expect(clock.getDate()).toBe(10)
  })

  it('crosses the date line where the zone does', () => {
    // 22:00 UTC Monday is already Tuesday morning in Tokyo.
    const clock = toZoneClock(new Date('2026-08-10T22:00:00Z'), TOKYO)

    expect(clock.getDate()).toBe(11)
    expect(clock.getHours()).toBe(7)
  })

  it('is stable either side of a DST change in the target zone', () => {
    // US DST ends 1 Nov 2026. 15:00 UTC is 11:00 EDT before, 10:00 EST after.
    expect(toZoneClock(new Date('2026-10-31T15:00:00Z'), NY).getHours()).toBe(11)
    expect(toZoneClock(new Date('2026-11-02T15:00:00Z'), NY).getHours()).toBe(10)
  })
})

describe('fromZoneClock', () => {
  it('inverts toZoneClock', () => {
    for (const iso of [
      '2026-08-10T14:00:00Z',
      '2026-01-15T03:30:00Z',
      '2026-11-02T15:00:00Z', // just after a DST change
    ]) {
      const instant = new Date(iso)
      const round = fromZoneClock(toZoneClock(instant, NY), NY)

      expect(round.toISOString()).toBe(instant.toISOString())
    }
  })

  it('round-trips through a zone ahead of UTC too', () => {
    const instant = new Date('2026-08-10T22:00:00Z')

    expect(
      fromZoneClock(toZoneClock(instant, TOKYO), TOKYO).toISOString(),
    ).toBe(instant.toISOString())
  })
})

describe('startOfWeekIn', () => {
  it('returns the Monday of the containing week', () => {
    // Wednesday 12 Aug 2026 -> Monday the 10th.
    const monday = startOfWeekIn(new Date('2026-08-12T18:00:00Z'), UTC)

    expect(monday.toISOString()).toBe('2026-08-10T00:00:00.000Z')
  })

  it('treats Sunday as the end of the week, not the start', () => {
    // The app is Monday-based throughout; getDay() is not.
    const monday = startOfWeekIn(new Date('2026-08-16T12:00:00Z'), UTC)

    expect(monday.toISOString()).toBe('2026-08-10T00:00:00.000Z')
  })

  it('is Monday local midnight in the user\'s zone, not the browser\'s', () => {
    const monday = startOfWeekIn(new Date('2026-08-12T18:00:00Z'), TOKYO)

    // Midnight Monday in Tokyo is the previous Sunday afternoon in UTC.
    expect(monday.toISOString()).toBe('2026-08-09T15:00:00.000Z')
    expect(toZoneClock(monday, TOKYO).getHours()).toBe(0)
  })

  it('lands on local midnight even when the week contains a DST change', () => {
    const monday = startOfWeekIn(new Date('2026-11-04T12:00:00Z'), NY)
    const clock = toZoneClock(monday, NY)

    expect(clock.getHours()).toBe(0)
    expect(clock.getDate()).toBe(2)
  })
})

describe('addWeeksIn', () => {
  it('advances by a week', () => {
    const next = addWeeksIn(new Date('2026-08-10T00:00:00Z'), 1, UTC)

    expect(next.toISOString()).toBe('2026-08-17T00:00:00.000Z')
  })

  it('goes backwards too', () => {
    const previous = addWeeksIn(new Date('2026-08-10T00:00:00Z'), -1, UTC)

    expect(previous.toISOString()).toBe('2026-08-03T00:00:00.000Z')
  })

  it('keeps local midnight across a DST boundary', () => {
    // The bug this exists for: adding 7x24h across the end of DST lands at
    // 23:00 the previous evening instead of midnight.
    const monday = startOfWeekIn(new Date('2026-10-28T12:00:00Z'), NY)
    const next = addWeeksIn(monday, 1, NY)
    const clock = toZoneClock(next, NY)

    expect(clock.getHours()).toBe(0)
    expect(clock.getDate()).toBe(2)
    expect(clock.getMonth()).toBe(10) // November

    // And the step really is not 7x24h, because an hour was given back.
    const hours = (next.getTime() - monday.getTime()) / 3_600_000
    expect(hours).toBe(169)
  })
})

describe('addDays', () => {
  it('does not mutate its argument', () => {
    const start = new Date(2026, 7, 10)
    const later = addDays(start, 3)

    expect(start.getDate()).toBe(10)
    expect(later.getDate()).toBe(13)
  })

  it('rolls over a month end', () => {
    expect(addDays(new Date(2026, 7, 30), 3).getMonth()).toBe(8)
  })
})

describe('isSameDay', () => {
  it('compares the calendar day, not the instant', () => {
    expect(isSameDay(new Date(2026, 7, 10, 1), new Date(2026, 7, 10, 23))).toBe(true)
    expect(isSameDay(new Date(2026, 7, 10, 23), new Date(2026, 7, 11, 1))).toBe(false)
  })

  it('does not confuse the same day in different years', () => {
    expect(isSameDay(new Date(2026, 7, 10), new Date(2027, 7, 10))).toBe(false)
  })
})

describe('minutesSinceMidnight', () => {
  it('converts a wall clock to minutes', () => {
    expect(minutesSinceMidnight(new Date(2026, 7, 10, 9, 30))).toBe(570)
    expect(minutesSinceMidnight(new Date(2026, 7, 10, 0, 0))).toBe(0)
    expect(minutesSinceMidnight(new Date(2026, 7, 10, 23, 59))).toBe(1439)
  })
})

describe('parseClockTime', () => {
  it('parses the "HH:MM:SS" the API sends', () => {
    expect(parseClockTime('09:00:00')).toBe(540)
    expect(parseClockTime('17:30:00')).toBe(1050)
  })

  it('copes with a value that omits the seconds', () => {
    expect(parseClockTime('09:00')).toBe(540)
  })

  it('reads midnight as zero rather than falsy-defaulting', () => {
    expect(parseClockTime('00:00:00')).toBe(0)
  })
})

describe('formatWeekRange', () => {
  it('collapses the month when both ends share it', () => {
    // Mon 10 - Sun 16 August.
    expect(formatWeekRange(new Date(2026, 7, 10))).toBe('Aug 10 – 16, 2026')
  })

  it('names both months when the week straddles them', () => {
    // Mon 27 July - Sun 2 August.
    expect(formatWeekRange(new Date(2026, 6, 27))).toBe('Jul 27 – Aug 2, 2026')
  })

  it('takes the year from the end of the week', () => {
    // Mon 28 Dec 2026 - Sun 3 Jan 2027.
    expect(formatWeekRange(new Date(2026, 11, 28))).toBe('Dec 28 – Jan 3, 2027')
  })
})
