import { useCallback, useEffect, useMemo, useState } from 'react'

import { EventEditor } from '../events/EventEditor'
import { ConfirmDialog } from '../schedule/ConfirmDialog'
import { GenerateDialog } from '../schedule/GenerateDialog'
import { MonthGrid } from '../schedule/MonthGrid'
import { ResolveDialog } from '../schedule/ResolveDialog'
import { TimeGrid } from '../schedule/TimeGrid'
import { generateSchedule } from '../schedule/generate'
import type { GenerateRequest, NeedsDecision } from '../schedule/generate'
import { SettledPeriod, deletePeriod } from '../schedule/periods'
import { isScheduleSpan } from '../schedule/types'
import type {
  Schedule as ScheduleData,
  ScheduleEvent,
  ScheduleSpan,
  ScheduleView,
} from '../schedule/types'
import { useAuth } from '../auth/useAuth'
import { readStored, store } from '../storage'
import {
  DAYS_IN_WEEK,
  MONTH_GRID_DAYS,
  addDays,
  addDaysIn,
  addMonthsIn,
  addWeeksIn,
  formatDayLabel,
  formatMonthLabel,
  formatWeekRange,
  startOfDayIn,
  startOfMonthGridIn,
  startOfWeekIn,
  toZoneClock,
} from '../schedule/week'

const VIEWS: { id: ScheduleView; label: string; hint: string }[] = [
  { id: 'generated', label: 'Schedule', hint: 'The periods ScheduleAssist built for you' },
  { id: 'calendar', label: 'Calendar', hint: 'Your calendars as you wrote them' },
]

const SPANS: { id: ScheduleSpan; label: string; hint: string }[] = [
  { id: 'day', label: 'Day', hint: 'One day, hour by hour' },
  { id: 'week', label: 'Week', hint: 'The default: a working week at a time' },
  { id: 'month', label: 'Month', hint: 'What is coming up, and how loaded each day is' },
]

/** Remembered per browser rather than per account: which span you like is a
 *  habit of the device you are on, and it needs no migration to store. */
const SPAN_KEY = 'sa-span'

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

/** Month draws no blocks, so most of the block grammar has nothing to key. */
const MONTH_LEGEND = [
  { kind: 'deadline', label: 'Deadline' },
  { kind: 'imported', label: 'Commitment' },
  { kind: 'manual', label: 'Added by you' },
]

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
  // Counted in whatever the current span is — days, weeks or months.
  const [offset, setOffset] = useState(0)
  const [span, setSpanState] = useState<ScheduleSpan>(() =>
    readStored(SPAN_KEY, isScheduleSpan, 'week'),
  )
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

  /** Switching span lands on today's day, week or month rather than trying to
   *  carry the date across. Converting between three units produces odd jumps
   *  at boundaries, and "take me to now" is the predictable answer. */
  const setSpan = useCallback((next: ScheduleSpan) => {
    setSpanState(next)
    setOffset(0)
    store(SPAN_KEY, next)
  }, [])

  // Keyed on the numeric value so the minute-by-minute `now` tick does not
  // churn the range; it only changes when the period on screen does.
  const anchor = useMemo(() => {
    const start =
      span === 'day'
        ? startOfDayIn(now, timeZone)
        : span === 'week'
          ? startOfWeekIn(now, timeZone)
          : startOfMonthGridIn(now, timeZone)
    return start.getTime()
  }, [span, now, timeZone])

  /** First instant on screen, and how many day columns it covers. A month grid
   *  starts on the Monday on or before the 1st, so its leading days are filled
   *  rather than blank. */
  const { rangeStart, dayCount } = useMemo(() => {
    const from = new Date(anchor)
    if (span === 'day') {
      return { rangeStart: addDaysIn(from, offset, timeZone), dayCount: 1 }
    }
    if (span === 'week') {
      return {
        rangeStart: addWeeksIn(from, offset, timeZone),
        dayCount: DAYS_IN_WEEK,
      }
    }
    // Stepping months from the *grid* start would drift, since that is usually
    // in the previous month. Step from the 1st, then find the grid again.
    const firstOfMonth = addDaysIn(from, 7, timeZone)
    const shifted = addMonthsIn(firstOfMonth, offset, timeZone)
    return {
      rangeStart: startOfMonthGridIn(shifted, timeZone),
      dayCount: MONTH_GRID_DAYS,
    }
  }, [anchor, offset, span, timeZone])

  /** The columns to draw, as zone-clock dates. */
  const days = useMemo(
    () =>
      Array.from({ length: dayCount }, (_, i) =>
        addDays(toZoneClock(rangeStart, timeZone), i),
      ),
    [rangeStart, dayCount, timeZone],
  )

  /** A day certain to be inside the month on screen — the grid's first cell
   *  usually is not, and the month heading depends on getting this right. */
  const monthOf = useMemo(
    () => (span === 'month' ? days[10] : days[0]),
    [days, span],
  )

  const load = useCallback(
    async (start: Date, count: number, which: ScheduleView, zone: string) => {
      setState({ status: 'loading' })
      // Counted in the user's zone, which is not always count x 24h.
      const end = addDaysIn(start, count, zone)
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
    void load(rangeStart, dayCount, view, timeZone)
  }, [load, rangeStart, dayCount, view, timeZone])

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
          await load(rangeStart, dayCount, view, timeZone)
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
    [load, rangeStart, dayCount, view, timeZone],
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
        await load(rangeStart, dayCount, view, timeZone)
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
    [load, rangeStart, dayCount, view, timeZone],
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

  /** Clicking a date in the month grid drops into that single day.
   *
   * The offset is in days once the span is `day`, so it is the distance from
   * today — which is exactly what the grid's own dates give us. */
  const openDay = useCallback(
    (day: Date) => {
      const today = toZoneClock(new Date(), timeZone)
      today.setHours(0, 0, 0, 0)
      const target = new Date(day)
      target.setHours(0, 0, 0, 0)
      // Both are zone-clock midnights, so a plain difference in days is safe
      // even across a DST boundary; rounding absorbs the stray hour.
      const days = Math.round(
        (target.getTime() - today.getTime()) / 86_400_000,
      )
      setSpanState('day')
      store(SPAN_KEY, 'day')
      setOffset(days)
    },
    [timeZone],
  )

  const heading =
    span === 'day'
      ? formatDayLabel(days[0])
      : span === 'week'
        ? formatWeekRange(days[0])
        : formatMonthLabel(monthOf)

  const legend = span === 'month' ? MONTH_LEGEND : LEGEND[view]

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
            onClick={() => setOffset((o) => o - 1)}
            aria-label={`Previous ${span}`}
          >
            ‹
          </button>
          <button
            className="icon-button"
            onClick={() => setOffset((o) => o + 1)}
            aria-label={`Next ${span}`}
          >
            ›
          </button>
          {/* Labelled in the user's zone, so the heading matches the columns. */}
          <h2>{heading}</h2>
          {offset !== 0 && (
            <button className="text-button" onClick={() => setOffset(0)}>
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

        {/* Two independent axes, as in Google Calendar: how much time is on
            screen, and which of the two readings of it you want. */}
        <div className="switch-row">
          <div className="view-switch" role="group" aria-label="Time span">
            {SPANS.map((option) => (
              <button
                key={option.id}
                type="button"
                className="choice"
                aria-pressed={span === option.id}
                onClick={() => setSpan(option.id)}
                title={option.hint}
              >
                {option.label}
              </button>
            ))}
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
        </div>

        <ul className="legend">
          {legend.map((item) => (
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
          <button className="button" onClick={() => void load(rangeStart, dayCount, view, timeZone)}>
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
                ? `Nothing scheduled this ${span} yet. Add a deadline, or mark one of your calendars as school or work so its due dates are picked up.`
                : `Nothing in your calendars this ${span}.`}
            </p>
          )}
          {span === 'month' ? (
            <MonthGrid
              schedule={state.data}
              days={days}
              monthOf={monthOf}
              now={now}
              onSelectEvent={(id) => void openEvent(id)}
              onSelectDay={openDay}
            />
          ) : (
            <TimeGrid
              schedule={state.data}
              days={days}
              now={now}
              onSelectEvent={(id) => void openEvent(id)}
              onDeletePeriod={handleDeletePeriod}
            />
          )}
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
