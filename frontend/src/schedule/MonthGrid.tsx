/** The month view: six rows of seven days, no time axis.
 *
 * Deliberately not a scaled-down week. There is no room to place blocks by the
 * hour, and no use for it either — a month is read to find what is coming, so
 * each cell lists what is on that day and how much work the app has allocated.
 *
 * The commitment horizon is not drawn here. It marks where the settled part of
 * the schedule ends, which means little when periods appear as a count rather
 * than as blocks, and a rule that wrapped across grid rows would read as a
 * mistake rather than a boundary. */

import { useMemo } from 'react'

import { formatPeriodLoad, monthCells } from './month'
import type { Schedule } from './types'
import { DAYS_IN_WEEK, isSameDay, toZoneClock } from './week'

type Props = {
  schedule: Schedule
  /** The 42 cells to draw, as zone-clock dates, starting on a Monday. */
  days: Date[]
  /** A day inside the month being shown — the grid's first cell usually is not. */
  monthOf: Date
  now: Date
  onSelectEvent?: (eventId: number) => void
  /** Opens a single day. The day number is the affordance, as in Google Calendar. */
  onSelectDay?: (day: Date) => void
}

export function MonthGrid({
  schedule,
  days,
  monthOf,
  now,
  onSelectEvent,
  onSelectDay,
}: Props) {
  const { events, periods, preferences } = schedule
  const timeZone = preferences.timezone

  const cells = useMemo(
    () => monthCells(events, periods, days, timeZone, monthOf),
    [events, periods, days, timeZone, monthOf],
  )
  const zonedNow = useMemo(() => toZoneClock(now, timeZone), [now, timeZone])
  const workdays = new Set(preferences.workdays)

  // Weekday headings come from the first row, so they are localised and
  // Monday-first without hardcoding names.
  const headings = days.slice(0, DAYS_IN_WEEK)

  return (
    <div className="month">
      <div className="month-head">
        {headings.map((day) => (
          <div key={day.toISOString()} className="month-dow">
            {day.toLocaleDateString([], { weekday: 'short' })}
          </div>
        ))}
      </div>

      <div className="month-grid">
        {cells.map((cell) => {
          const isToday = isSameDay(cell.day, zonedNow)
          const isWorkday = workdays.has((cell.day.getDay() + 6) % 7)
          const load = formatPeriodLoad(cell.periodCount, cell.periodMinutes)

          return (
            <div
              key={cell.key}
              className={`month-cell${cell.inMonth ? '' : ' is-outside'}${
                isToday ? ' is-today' : ''
              }${isWorkday ? '' : ' is-off'}`}
            >
              <div className="month-cell-head">
                {onSelectDay ? (
                  <button
                    type="button"
                    className="month-date"
                    onClick={() => onSelectDay(cell.day)}
                    aria-label={`Open ${cell.day.toLocaleDateString([], {
                      weekday: 'long',
                      month: 'long',
                      day: 'numeric',
                    })}`}
                  >
                    {cell.day.getDate()}
                  </button>
                ) : (
                  <span className="month-date">{cell.day.getDate()}</span>
                )}
                {isToday && <span className="sr-only">(today)</span>}
              </div>

              <div className="month-chips">
                {cell.chips.map((chip) => (
                  <button
                    key={chip.key}
                    type="button"
                    className={`month-chip kind-${chip.kind}`}
                    title={`${chip.title} — ${chip.when}`}
                    onClick={() => onSelectEvent?.(chip.eventId)}
                  >
                    <span className="month-chip-title">{chip.title}</span>
                    <span className="month-chip-when">{chip.when}</span>
                  </button>
                ))}

                {cell.hiddenCount > 0 && (
                  <span className="month-more">+{cell.hiddenCount} more</span>
                )}
              </div>

              {load && <div className="month-load">{load}</div>}
            </div>
          )
        })}
      </div>
    </div>
  )
}
