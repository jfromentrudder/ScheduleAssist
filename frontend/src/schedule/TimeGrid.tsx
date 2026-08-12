import { useEffect, useMemo, useRef } from 'react'

import {
  MINUTES_IN_DAY,
  allDayEvents,
  buildDayBlocks,
  buildDeadlineMarkers,
  buildWorkWindows,
  openingMinute,
} from './layout'
import type { Schedule } from './types'
import {
  formatHour,
  isSameDay,
  minutesSinceMidnight,
  parseClockTime,
  toZoneClock,
} from './week'

const PX_PER_MINUTE = 0.9

type Props = {
  schedule: Schedule
  /** The columns to draw, as zone-clock dates — one for a day view, seven for a
   *  week. The grid itself is indifferent to how many there are. */
  days: Date[]
  now: Date
  /** Opens an event's detail. Periods are generated, so they are not editable. */
  onSelectEvent?: (eventId: number) => void
  /** Removes a generated block. `settled` is passed through so the caller can
   *  warn before touching something inside the horizon. */
  onDeletePeriod?: (periodId: number, settled: boolean) => void
}

/** The time-axis calendar: a scrollable 24-hour grid over one or more days. */
export function TimeGrid({
  schedule,
  days,
  now,
  onSelectEvent,
  onDeletePeriod,
}: Props) {
  const { events, periods, preferences } = schedule
  const timeZone = preferences.timezone

  const zonedNow = useMemo(() => toZoneClock(now, timeZone), [now, timeZone])

  const perDay = useMemo(
    () =>
      days.map((day) => ({
        day,
        blocks: buildDayBlocks(events, periods, day, timeZone),
        markers: buildDeadlineMarkers(events, day, timeZone),
        allDay: allDayEvents(events, day, timeZone),
        windows: buildWorkWindows(events, day, timeZone),
      })),
    [days, events, periods, timeZone],
  )

  // The whole day is always drawn — midnight to midnight — so nothing is ever
  // clipped and the user can reach any hour by scrolling.
  const bodyHeight = MINUTES_IN_DAY * PX_PER_MINUTE
  const offsetOf = (minutes: number) => minutes * PX_PER_MINUTE

  const hourLines = useMemo(() => {
    const hours: number[] = []
    for (let m = 0; m <= MINUTES_IN_DAY; m += 60) hours.push(m)
    return hours
  }, [])

  const openAt = useMemo(
    () =>
      openingMinute(
        perDay.map((d) => d.blocks),
        perDay.map((d) => d.markers),
        parseClockTime(preferences.day_start),
        perDay.map((d) => d.windows),
      ),
    [perDay, preferences.day_start],
  )

  const scroller = useRef<HTMLDivElement>(null)

  // Opens on the working day rather than on midnight. Re-runs when the week
  // changes, and when `openAt` itself moves — something newly scheduled before
  // the user's usual hours is worth bringing into view.
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTop = openAt * PX_PER_MINUTE
  }, [openAt, days])

  const workdays = new Set(preferences.workdays)
  const hasAllDay = perDay.some((d) => d.allDay.length > 0)
  // No visibility check needed: every minute of the day is on the grid now.
  const nowMinutes = minutesSinceMidnight(zonedNow)

  // The horizon always lands on a local midnight, so it separates whole day
  // columns rather than cutting through one. The calendar view has no periods
  // to settle, so it does not draw the rule at all.
  const horizonEnd = schedule.horizon_ends_at
    ? toZoneClock(new Date(schedule.horizon_ends_at), timeZone)
    : null
  const isSettled = (day: Date) => horizonEnd !== null && day < horizonEnd
  // Mark the first open day only when a settled one precedes it, so the rule
  // is not drawn against the left edge of a week that is entirely open.
  const horizonIndex = days.findIndex(
    (day, i) => !isSettled(day) && i > 0 && isSettled(days[i - 1]),
  )

  return (
    <div
      className="week"
      style={
        {
          '--px-per-minute': PX_PER_MINUTE,
          // Drives the column template, so one day fills the width the same way
          // seven share it.
          '--day-count': days.length,
        } as React.CSSProperties
      }
    >
      {/* The day headings scroll in the same box as the columns they label, and
          stick to the top of it. Keeping them outside would let a scrollbar
          narrow the body without narrowing the header, drifting every column
          out of line with its own date. */}
      <div className="week-scroll" ref={scroller}>
        <div className="week-frozen">
          <div className="week-head">
            <div className="week-gutter" aria-hidden="true" />
            {days.map((day, i) => {
              const isToday = isSameDay(day, zonedNow)
              const isWorkday = workdays.has((day.getDay() + 6) % 7)
              return (
                <div
                  key={day.toISOString()}
                  className={`week-day-head${isToday ? ' is-today' : ''}${isWorkday ? '' : ' is-off'}${i === horizonIndex ? ' is-horizon' : ''}`}
                >
                  <span className="week-dow">
                    {day.toLocaleDateString([], { weekday: 'short' })}
                  </span>
                  <span className="week-date">
                    {day.getDate()}
                    {isToday && <span className="sr-only"> (today)</span>}
                  </span>
                </div>
              )
            })}
          </div>

          {hasAllDay && (
            <div className="week-allday">
              <div className="week-gutter">All day</div>
              {perDay.map(({ day, allDay }) => (
                <div key={day.toISOString()} className="week-allday-cell">
                  {allDay.map((event) => (
                    <span key={event.id} className={`chip kind-${event.source}`}>
                      {event.title}
                    </span>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="week-body" style={{ height: `${bodyHeight}px` }}>
        <div className="week-gutter week-hours">
          {hourLines.map((minutes) => (
            <span key={minutes} className="week-hour" style={{ top: `${offsetOf(minutes)}px` }}>
              {formatHour(minutes)}
            </span>
          ))}
        </div>

        {perDay.map(({ day, blocks, markers, windows }, i) => {
          const isToday = isSameDay(day, zonedNow)
          const isWorkday = workdays.has((day.getDay() + 6) % 7)
          return (
            <div
              key={day.toISOString()}
              className={`week-col${isToday ? ' is-today' : ''}${isWorkday ? '' : ' is-off'}${i === horizonIndex ? ' is-horizon' : ''}`}
            >
              {hourLines.map((minutes) => (
                <div key={minutes} className="week-line" style={{ top: `${offsetOf(minutes)}px` }} />
              ))}

              {/* Behind everything: periods sit inside these, not beside them. */}
              {windows.map((window) => (
                <button
                  key={window.key}
                  type="button"
                  className="work-window"
                  style={{
                    top: `${offsetOf(window.startMin)}px`,
                    height: `${(window.endMin - window.startMin) * PX_PER_MINUTE}px`,
                  }}
                  onClick={() => onSelectEvent?.(window.eventId)}
                >
                  <span className="work-window-label">{window.title}</span>
                </button>
              ))}

              {blocks.map((block) => {
                const classes = `block kind-${block.kind}${
                  block.locked ? ' is-locked' : ''
                }${block.eventId && onSelectEvent ? ' is-clickable' : ''}`
                const style = {
                  top: `${offsetOf(block.startMin)}px`,
                  height: `${(block.endMin - block.startMin) * PX_PER_MINUTE}px`,
                  left: `${(block.lane / block.laneCount) * 100}%`,
                  width: `${(1 / block.laneCount) * 100}%`,
                }
                const inner = (
                  <>
                    <span className="block-title">{block.title}</span>
                    <span className="block-sub">{block.subtitle}</span>
                  </>
                )

                const open =
                  block.eventId !== undefined && onSelectEvent
                    ? () => onSelectEvent(block.eventId!)
                    : null
                const remove =
                  block.periodId !== undefined && onDeletePeriod
                    ? () => onDeletePeriod(block.periodId!, block.locked ?? false)
                    : null

                // A deletable block holds its own button, so it cannot be one
                // itself: nested interactive elements are invalid markup and
                // unreachable by keyboard. Periods therefore render as a
                // container, and only events become a single large target.
                if (remove) {
                  return (
                    <article key={block.key} className={classes} style={style}>
                      {open ? (
                        <button
                          type="button"
                          className="block-open"
                          onClick={open}
                        >
                          {inner}
                        </button>
                      ) : (
                        inner
                      )}
                      <button
                        type="button"
                        className="block-delete"
                        aria-label={`Delete ${block.title}`}
                        title="Delete this period"
                        onClick={remove}
                      >
                        ×
                      </button>
                    </article>
                  )
                }

                return open ? (
                  <button
                    key={block.key}
                    type="button"
                    className={classes}
                    style={style}
                    onClick={open}
                  >
                    {inner}
                  </button>
                ) : (
                  <article key={block.key} className={classes} style={style}>
                    {inner}
                  </article>
                )
              })}

              {markers.map((marker) => (
                <div
                  key={marker.key}
                  className="deadline"
                  style={{ top: `${offsetOf(marker.atMin)}px` }}
                >
                  <button
                    type="button"
                    className="deadline-flag"
                    onClick={() => onSelectEvent?.(marker.eventId)}
                  >
                    Due: {marker.title}
                  </button>
                </div>
              ))}

              {isToday && (
                <div
                  className="now-line"
                  style={{ top: `${offsetOf(nowMinutes)}px` }}
                  aria-label="Current time"
                />
              )}
            </div>
          )
        })}
        </div>
      </div>
    </div>
  )
}
