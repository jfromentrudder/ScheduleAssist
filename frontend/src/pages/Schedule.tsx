import { useCallback, useEffect, useMemo, useState } from 'react'

import { EventEditor } from '../events/EventEditor'
import { ConfirmDialog } from '../schedule/ConfirmDialog'
import { GenerateDialog } from '../schedule/GenerateDialog'
import { ResolveDialog } from '../schedule/ResolveDialog'
import { WeekView } from '../schedule/WeekView'
import { generateSchedule } from '../schedule/generate'
import type { GenerateRequest, NeedsDecision } from '../schedule/generate'
import { SettledPeriod, deletePeriod } from '../schedule/periods'
import type {
  Schedule as ScheduleData,
  ScheduleEvent,
  ScheduleView,
} from '../schedule/types'
import { useAuth } from '../auth/useAuth'
import {
  addWeeksIn,
  formatWeekRange,
  startOfWeekIn,
  toZoneClock,
} from '../schedule/week'

const VIEWS: { id: ScheduleView; label: string; hint: string }[] = [
  { id: 'generated', label: 'Schedule', hint: 'The periods ScheduleAssist built for you' },
  { id: 'calendar', label: 'Calendar', hint: 'Your calendars as you wrote them' },
]

/** The two views share only commitments, so their legends differ too —
 *  offering a "Work period" key on a view that has none is just noise. */
const LEGEND: Record<ScheduleView, { kind: string; label: string }[]> = {
  generated: [
    { kind: 'period', label: 'Work period' },
    { kind: 'settled', label: 'Settled' },
    { kind: 'meal', label: 'Meal break' },
    { kind: 'deadline', label: 'Deadline' },
    { kind: 'imported', label: 'Commitment' },
    { kind: 'manual', label: 'Added by you' },
  ],
  calendar: [
    { kind: 'imported', label: 'From calendar' },
    { kind: 'manual', label: 'Added by you' },
    { kind: 'deadline', label: 'Deadline' },
  ],
}

/** Open editor state: an existing event, or `true` while creating a new one. */
type Editing = ScheduleEvent | true | null

/** A settled period the user has asked to delete, with the server's reason. */
type PendingDelete = { periodId: number; message: string }

const SETTLED_FALLBACK =
  'That period is settled — it sits inside your planning horizon. Deleting it ' +
  'frees the time, but the work it was holding will be scheduled again the ' +
  'next time you generate.'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: ScheduleData }

export function Schedule() {
  // The week shown is the user's week, which is not the browser's when the two
  // are in different zones. Their timezone arrives with /api/auth/me, so it is
  // known before the first fetch.
  const { user } = useAuth()
  const timeZone =
    user?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone

  // Held as an offset rather than a date: the timezone arrives after the first
  // render, and a stored date would be stuck in whatever zone was guessed then.
  const [weekOffset, setWeekOffset] = useState(0)
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  // Updated periodically so the "current time" line stays accurate.
  const [now, setNow] = useState(() => new Date())
  const [generating, setGenerating] = useState(false)
  // Set only when the server needs the user to choose how to resolve a
  // shortfall. Until it is cleared, nothing has been written.
  const [decision, setDecision] = useState<NeedsDecision | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [view, setView] = useState<ScheduleView>('generated')
  const [editing, setEditing] = useState<Editing>(null)
  // Open between clicking Generate and choosing what to do, so a misclick can
  // be closed without anything having been written.
  const [asking, setAsking] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null)
  const [removing, setRemoving] = useState(false)

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(id)
  }, [])

  // Keyed on the numeric value so the minute-by-minute `now` tick does not
  // churn the week; it only changes when the week itself does.
  const currentWeek = useMemo(
    () => startOfWeekIn(now, timeZone).getTime(),
    [now, timeZone],
  )
  const weekStart = useMemo(
    () => addWeeksIn(new Date(currentWeek), weekOffset, timeZone),
    [currentWeek, weekOffset, timeZone],
  )

  const load = useCallback(
    async (start: Date, which: ScheduleView, zone: string) => {
      setState({ status: 'loading' })
      // A week in the user's zone, which is not always 7 x 24h.
      const end = addWeeksIn(start, 1, zone)
      const params = new URLSearchParams({
        start: start.toISOString(),
        end: end.toISOString(),
        view: which,
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
    },
    [],
  )

  useEffect(() => {
    void load(weekStart, view, timeZone)
  }, [load, weekStart, view, timeZone])

  const runGenerate = useCallback(
    async (request: GenerateRequest = {}) => {
      setGenerating(true)
      setNotice(null)
      setAsking(false)
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
          await load(weekStart, view, timeZone)
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
    [load, weekStart, view, timeZone],
  )

  /** Saving an event changes what the generator has to work with, so the
   *  schedule is rebuilt straight away rather than waiting to be asked.
   *
   *  No prompt here on purpose: this is automatic regeneration, which always
   *  respects the freeze. Overriding it is something the user has to ask for. */
  const handleSaved = useCallback(async () => {
    setEditing(null)
    await runGenerate()
  }, [runGenerate])

  /** Removes a generated block.
   *
   *  Deliberately does not regenerate afterwards. The user has just said they
   *  do not want that block, and an automatic pass would put it straight back. */
  const removePeriod = useCallback(
    async (periodId: number, confirmed: boolean) => {
      setRemoving(true)
      setNotice(null)
      try {
        await deletePeriod(periodId, confirmed)
        setPendingDelete(null)
        await load(weekStart, view, timeZone)
      } catch (failure) {
        if (failure instanceof SettledPeriod) {
          // Settled since this page loaded, or clicked from a stale view. The
          // server decides, so its wording is what the user is shown.
          setPendingDelete({ periodId, message: failure.message })
        } else {
          setNotice(
            failure instanceof Error
              ? failure.message
              : 'Could not delete that period.',
          )
        }
      } finally {
        setRemoving(false)
      }
    },
    [load, weekStart, view, timeZone],
  )

  const handleDeletePeriod = useCallback(
    (periodId: number, settled: boolean) => {
      // The feed already carries `locked`, so the warning appears without a
      // round-trip; the 409 handled above is the backstop for a stale page.
      if (settled) {
        setPendingDelete({ periodId, message: SETTLED_FALLBACK })
        return
      }
      void removePeriod(periodId, false)
    },
    [removePeriod],
  )

  /** Opens an event's detail, fetching it when it is not on screen.
   *
   * A period can serve a deadline in a later week, so the block the user
   * clicked may have no matching event in the loaded feed. */
  const openEvent = useCallback(
    async (id: number) => {
      if (state.status === 'ready') {
        const found = state.data.events.find((e) => e.id === id)
        if (found) {
          setEditing(found)
          return
        }
      }
      const res = await fetch(`/api/events/${id}`)
      if (res.ok) setEditing(await res.json())
      else setNotice('Could not open that event.')
    },
    [state],
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

  const isCurrentWeek = weekOffset === 0

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
            onClick={() => setWeekOffset((w) => w - 1)}
            aria-label="Previous week"
          >
            ‹
          </button>
          <button
            className="icon-button"
            onClick={() => setWeekOffset((w) => w + 1)}
            aria-label="Next week"
          >
            ›
          </button>
          {/* Labelled in the user's zone, so the heading matches the columns. */}
          <h2>{formatWeekRange(toZoneClock(weekStart, timeZone))}</h2>
          {!isCurrentWeek && (
            <button className="text-button" onClick={() => setWeekOffset(0)}>
              Today
            </button>
          )}
          {/* Generating from the calendar view would produce nothing you can
              see there, so the action lives with its result. */}
          {view === 'generated' && (
            <button
              className="button"
              onClick={() => setAsking(true)}
              disabled={generating || state.status !== 'ready'}
            >
              {generating ? 'Generating…' : 'Generate schedule'}
            </button>
          )}
          <button className="button quiet" onClick={() => setEditing(true)}>
            Add event
          </button>
        </div>

        <div className="view-switch" role="group" aria-label="View">
          {VIEWS.map((option) => (
            <button
              key={option.id}
              type="button"
              className="choice"
              aria-pressed={view === option.id}
              onClick={() => setView(option.id)}
              title={option.hint}
            >
              {option.label}
            </button>
          ))}
        </div>

        <ul className="legend">
          {LEGEND[view].map((item) => (
            <li key={item.kind}>
              <span className={`swatch kind-${item.kind}`} /> {item.label}
            </li>
          ))}
        </ul>
      </header>

      {state.status === 'loading' && (
        <p className="schedule-status">Loading your schedule…</p>
      )}

      {state.status === 'error' && (
        <div className="schedule-status" role="alert">
          <p>{state.message}</p>
          <button className="button" onClick={() => void load(weekStart, view, timeZone)}>
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
              {view === 'generated'
                ? 'Nothing scheduled this week yet. Add a deadline, or mark one of your calendars as school or work so its due dates are picked up.'
                : 'Nothing in your calendars this week.'}
            </p>
          )}
          <WeekView
            schedule={state.data}
            weekStart={weekStart}
            now={now}
            onSelectEvent={(id) => void openEvent(id)}
            onDeletePeriod={handleDeletePeriod}
          />
        </>
      )}

      {asking && state.status === 'ready' && (
        <GenerateDialog
          horizonDays={state.data.preferences.schedule_horizon_days}
          busy={generating}
          onGenerate={(request) => void runGenerate(request)}
          onClose={() => setAsking(false)}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="This period is settled"
          message={pendingDelete.message}
          confirmLabel="Delete it anyway"
          busy={removing}
          onConfirm={() => void removePeriod(pendingDelete.periodId, true)}
          onCancel={() => setPendingDelete(null)}
        />
      )}

      {editing && (
        <EventEditor
          event={editing === true ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => void handleSaved()}
        />
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
