import { useCallback, useEffect, useState } from 'react'

import { ResolveDialog } from '../schedule/ResolveDialog'
import { WeekView } from '../schedule/WeekView'
import { generateSchedule } from '../schedule/generate'
import type { GenerateRequest, NeedsDecision } from '../schedule/generate'
import type { Schedule as ScheduleData } from '../schedule/types'
import { DAYS_IN_WEEK, addDays, formatWeekRange, startOfWeek } from '../schedule/week'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: ScheduleData }

export function Schedule() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  // Updated periodically so the "current time" line stays accurate.
  const [now, setNow] = useState(() => new Date())
  const [generating, setGenerating] = useState(false)
  // Set only when the server needs the user to choose how to resolve a
  // shortfall. Until it is cleared, nothing has been written.
  const [decision, setDecision] = useState<NeedsDecision | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])

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

  const runGenerate = useCallback(
    async (request: GenerateRequest = {}) => {
      setGenerating(true)
      setNotice(null)
      try {
        const result = await generateSchedule(request)
        if (result.committed) {
          setDecision(null)
          const kept = result.periods_kept
          setNotice(
            `Scheduled ${result.periods_created} new ${
              result.periods_created === 1 ? 'period' : 'periods'
            }${kept ? `, keeping ${kept} already settled` : ''}.`,
          )
          await load(weekStart)
        } else {
          // Nothing written yet — hand the choice to the user.
          setDecision(result)
        }
      } catch {
        setNotice('Could not generate your schedule. Please try again.')
      } finally {
        setGenerating(false)
      }
    },
    [load, weekStart],
  )

  const titleOf = useCallback(
    (eventId: number) => {
      if (state.status !== 'ready') return 'this deadline'
      return (
        state.data.events.find((e) => e.id === eventId)?.title ??
        'a deadline outside this week'
      )
    },
    [state],
  )

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
          <button
            className="button"
            onClick={() => void runGenerate()}
            disabled={generating || state.status !== 'ready'}
          >
            {generating ? 'Generating…' : 'Generate schedule'}
          </button>
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
            <span className="swatch kind-settled" /> Settled
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
          <button className="button" onClick={() => void load(weekStart)}>
            Try again
          </button>
        </div>
      )}

      {notice && (
        <p className="schedule-status" role="status">
          {notice}
        </p>
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

      {decision && (
        <ResolveDialog
          result={decision}
          titleOf={titleOf}
          busy={generating}
          onResolve={(request) => void runGenerate(request)}
          onCancel={() => setDecision(null)}
        />
      )}
    </section>
  )
}
