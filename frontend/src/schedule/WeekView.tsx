import { useMemo } from 'react'

import {
  allDayEvents,
  buildDayBlocks,
  buildDeadlineMarkers,
  buildWorkWindows,
  gridBounds,
} from './layout'
import type { Schedule } from './types'
import {
  DAYS_IN_WEEK,
  addDays,
  formatHour,
  isSameDay,
  minutesSinceMidnight,
  parseClockTime,
  toZoneClock,
} from './week'

const PX_PER_MINUTE = 0.9

type Props = {
  schedule: Schedule
  weekStart: Date
  now: Date
  /** Opens an event's detail. Periods are generated, so they are not editable. */
  onSelectEvent?: (eventId: number) => void
}

export function WeekView({ schedule, weekStart, now, onSelectEvent }: Props) {
  const { events, periods, preferences } = schedule
  const timeZone = preferences.timezone

  // Everything below positions blocks with ordinary local date methods, so
  // instants are converted once here into the user's zone. These are display
  // values only — `weekStart` and `now` stay real instants for their callers.
  const days = useMemo(
    () =>
      Array.from({ length: DAYS_IN_WEEK }, (_, i) =>
        addDays(toZoneClock(weekStart, timeZone), i),
      ),
    [weekStart, timeZone],
  )
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

  const bounds = useMemo(
    () =>
      gridBounds(
        perDay.map((d) => d.blocks),
        perDay.map((d) => d.markers),
        parseClockTime(preferences.day_start),
        parseClockTime(preferences.day_end),
        perDay.map((d) => d.windows),
      ),
    [perDay, preferences.day_start, preferences.day_end],
  )

  const totalMinutes = bounds.endMin - bounds.startMin
  const bodyHeight = totalMinutes * PX_PER_MINUTE
  const offsetOf = (minutes: number) => (minutes - bounds.startMin) * PX_PER_MINUTE

  const hourLines = useMemo(() => {
    const hours: number[] = []
    for (let m = bounds.startMin; m <= bounds.endMin; m += 60) hours.push(m)
    return hours
  }, [bounds.startMin, bounds.endMin])

  const workdays = new Set(preferences.workdays)
  const hasAllDay = perDay.some((d) => d.allDay.length > 0)
  const nowMinutes = minutesSinceMidnight(zonedNow)
  const nowVisible = nowMinutes >= bounds.startMin && nowMinutes <= bounds.endMin

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
    <div className="week" style={{ '--px-per-minute': PX_PER_MINUTE } as React.CSSProperties}>
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

                // Only events open a detail panel; periods are generated
                // output, so there is nothing on them to edit.
                return block.eventId && onSelectEvent ? (
                  <button
                    key={block.key}
                    type="button"
                    className={classes}
                    style={style}
                    onClick={() => onSelectEvent(block.eventId!)}
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

              {isToday && nowVisible && (
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
  )
}
