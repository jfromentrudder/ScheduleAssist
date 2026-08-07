import { useMemo } from 'react'

import {
  allDayEvents,
  buildDayBlocks,
  buildDeadlineMarkers,
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
} from './week'

const PX_PER_MINUTE = 0.9

type Props = {
  schedule: Schedule
  weekStart: Date
  now: Date
}

export function WeekView({ schedule, weekStart, now }: Props) {
  const days = useMemo(
    () => Array.from({ length: DAYS_IN_WEEK }, (_, i) => addDays(weekStart, i)),
    [weekStart],
  )

  const { events, periods, preferences } = schedule

  const perDay = useMemo(
    () =>
      days.map((day) => ({
        day,
        blocks: buildDayBlocks(events, periods, day),
        markers: buildDeadlineMarkers(events, day),
        allDay: allDayEvents(events, day),
      })),
    [days, events, periods],
  )

  const bounds = useMemo(
    () =>
      gridBounds(
        perDay.map((d) => d.blocks),
        perDay.map((d) => d.markers),
        parseClockTime(preferences.day_start),
        parseClockTime(preferences.day_end),
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
  const nowMinutes = minutesSinceMidnight(now)
  const nowVisible = nowMinutes >= bounds.startMin && nowMinutes <= bounds.endMin

  // The horizon always lands on a local midnight, so it separates whole day
  // columns rather than cutting through one.
  const horizonEnd = new Date(schedule.horizon_ends_at)
  const isSettled = (day: Date) => day < horizonEnd
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
          const isToday = isSameDay(day, now)
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

        {perDay.map(({ day, blocks, markers }, i) => {
          const isToday = isSameDay(day, now)
          const isWorkday = workdays.has((day.getDay() + 6) % 7)
          return (
            <div
              key={day.toISOString()}
              className={`week-col${isToday ? ' is-today' : ''}${isWorkday ? '' : ' is-off'}${i === horizonIndex ? ' is-horizon' : ''}`}
            >
              {hourLines.map((minutes) => (
                <div key={minutes} className="week-line" style={{ top: `${offsetOf(minutes)}px` }} />
              ))}

              {blocks.map((block) => (
                <article
                  key={block.key}
                  className={`block kind-${block.kind}${block.locked ? ' is-locked' : ''}`}
                  style={{
                    top: `${offsetOf(block.startMin)}px`,
                    height: `${(block.endMin - block.startMin) * PX_PER_MINUTE}px`,
                    left: `${(block.lane / block.laneCount) * 100}%`,
                    width: `${(1 / block.laneCount) * 100}%`,
                  }}
                >
                  <span className="block-title">{block.title}</span>
                  <span className="block-sub">{block.subtitle}</span>
                </article>
              ))}

              {markers.map((marker) => (
                <div
                  key={marker.key}
                  className="deadline"
                  style={{ top: `${offsetOf(marker.atMin)}px` }}
                >
                  <span className="deadline-flag">Due: {marker.title}</span>
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
