import { useCallback, useEffect, useState } from 'react'

import { WeekView } from '../schedule/WeekView'
import type { Schedule as ScheduleData } from '../schedule/types'
import { DAYS_IN_WEEK, addDays, formatWeekRange, startOfWeek } from '../schedule/week'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: ScheduleData }

export function Schedule() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  // Fixed per render pass so the "today" highlight can't drift mid-week-change.
  const [now] = useState(() => new Date())

  const load = useCallback(async (start: Date) => {
    setState({ status: 'loading' })
    const end = addDays(start, DAYS_IN_WEEK)
    const params = new URLSearchParams({
      start: start.toISOString(),
      end: end.toISOString(),
    })

    try {
      const res = await fetch(`/api/schedule?${params}`)
      if (!res.ok) throw new Error(`Request failed (${res.status})`)
      setState({ status: 'ready', data: await res.json() })
    } catch {
      setState({
        status: 'error',
        message: 'Could not load your schedule.',
      })
    }
  }, [])

  useEffect(() => {
    void load(weekStart)
  }, [load, weekStart])

  const thisWeek = startOfWeek(now)
  const isCurrentWeek = weekStart.getTime() === thisWeek.getTime()

  const isEmpty =
    state.status === 'ready' &&
    state.data.events.length === 0 &&
    state.data.periods.length === 0

  return (
    <section className="schedule">
      <header className="schedule-bar">
        <div className="schedule-nav">
          <button
            className="icon-button"
            onClick={() => setWeekStart((w) => addDays(w, -DAYS_IN_WEEK))}
            aria-label="Previous week"
          >
            ‹
          </button>
          <button
            className="icon-button"
            onClick={() => setWeekStart((w) => addDays(w, DAYS_IN_WEEK))}
            aria-label="Next week"
          >
            ›
          </button>
          <h2>{formatWeekRange(weekStart)}</h2>
          {!isCurrentWeek && (
            <button className="text-button" onClick={() => setWeekStart(thisWeek)}>
              Today
            </button>
          )}
        </div>

        <ul className="legend">
          <li>
            <span className="swatch kind-imported" /> From calendar
          </li>
          <li>
            <span className="swatch kind-manual" /> Added by you
          </li>
          <li>
            <span className="swatch kind-period" /> Work period
          </li>
          <li>
            <span className="swatch kind-deadline" /> Deadline
          </li>
        </ul>
      </header>

      {state.status === 'loading' && (
        <p className="schedule-status">Loading your schedule…</p>
      )}

      {state.status === 'error' && (
        <div className="schedule-status" role="alert">
          <p>{state.message}</p>
          <button className="counter" onClick={() => void load(weekStart)}>
            Try again
          </button>
        </div>
      )}

      {state.status === 'ready' && (
        <>
          {isEmpty && (
            <p className="schedule-status">
              Nothing scheduled this week. Connect a calendar or add an event to get
              started.
            </p>
          )}
          <WeekView schedule={state.data} weekStart={weekStart} now={now} />
        </>
      )}
    </section>
  )
}
