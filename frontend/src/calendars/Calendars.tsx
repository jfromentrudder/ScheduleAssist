/** Connect and manage calendar accounts (issue #7).
 *
 * Connecting leaves the app entirely — the browser goes to Google's consent
 * screen and comes back to /settings with a query flag — so this component
 * reads that flag on mount rather than awaiting a promise. */

import { useCallback, useEffect, useState } from 'react'

export type CalendarKind = 'school' | 'work' | 'personal'

/** One calendar inside a connected account — the checkbox rows Google shows
 *  down its left edge, and Apple nests under each account. */
export type Calendar = {
  id: number
  name: string
  description: string | null
  color: string | null
  is_primary: boolean
  selected: boolean
  kind: CalendarKind
  last_synced_at: string | null
  last_sync_error: string | null
}

export type Connection = {
  id: number
  provider: string
  account_email: string | null
  /** Seeds calendars discovered later; each calendar carries its own kind. */
  default_kind: CalendarKind
  created_at: string
  last_synced_at: string | null
  last_sync_error: string | null
  /** False once the grant is no longer refreshable; needs reconnecting. */
  healthy: boolean
  calendars: Calendar[]
}

const KINDS: { id: CalendarKind; label: string; hint: string }[] = [
  { id: 'school', label: 'School', hint: 'Assignments and due dates' },
  { id: 'work', label: 'Work', hint: 'Meetings and commitments' },
  { id: 'personal', label: 'Personal', hint: 'Everything else' },
]

/** Errors the callback can hand back, each with a way forward. */
const CONNECT_ERRORS: Record<string, string> = {
  denied:
    'Calendar access was not granted. You can try connecting again whenever you like.',
  scope:
    'ScheduleAssist needs permission to read your calendar. Please try again and leave the calendar permission ticked.',
  identity:
    'Google did not tell us which account that was. Please try connecting again.',
}

export function Calendars() {
  const [connections, setConnections] = useState<Connection[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<CalendarKind>('school')
  const [busyId, setBusyId] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/calendars')
      if (!res.ok) throw new Error('load failed')
      setConnections((await res.json()).connections)
    } catch {
      setError('Could not load your connected calendars.')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // The consent flow returns here with its outcome in the query string.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const failure = params.get('calendar_error')
    if (failure) setError(CONNECT_ERRORS[failure] ?? CONNECT_ERRORS.denied)
    if (failure || params.get('calendar_connected')) {
      // Clear the flag so a refresh does not replay the message.
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  function connect() {
    // A full navigation, not fetch: the consent screen is Google's page.
    window.location.href = `/api/calendars/google/connect?kind=${kind}`
  }

  async function updateCalendar(
    connection: Connection,
    calendar: Calendar,
    change: { selected?: boolean; kind?: CalendarKind },
  ) {
    setBusyId(connection.id)
    setNotice(null)
    const res = await fetch(
      `/api/calendars/${connection.id}/calendars/${calendar.id}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(change),
      },
    )
    if (res.ok) {
      const result = await res.json()
      if (result.events_removed)
        setNotice(`Removed ${result.events_removed} events from ${calendar.name}.`)
      else if (result.events_imported)
        setNotice(`Imported ${result.events_imported} events from ${calendar.name}.`)
      await load()
    } else if (res.status === 409) {
      setError('That account needs reconnecting before it can sync.')
    } else {
      setError(`Could not update ${calendar.name}.`)
    }
    setBusyId(null)
  }

  async function resync(connection: Connection) {
    setBusyId(connection.id)
    setNotice(null)
    const res = await fetch(`/api/calendars/${connection.id}/sync`, {
      method: 'POST',
    })
    if (res.ok) {
      const result = await res.json()
      const changed =
        result.created + result.updated + result.deleted === 0
          ? 'Already up to date.'
          : `Imported ${result.created} new, updated ${result.updated}, removed ${result.deleted}.`
      setNotice(changed)
      await load()
    } else if (res.status === 409) {
      // The grant is gone; only reconnecting fixes it.
      setError('That calendar needs reconnecting before it can sync.')
      await load()
    } else {
      setError('Could not sync that calendar.')
    }
    setBusyId(null)
  }

  async function remove(connection: Connection) {
    const label = connection.account_email ?? 'this calendar'
    if (
      !confirm(
        `Disconnect ${label}? Events imported from it will be removed from your schedule.`,
      )
    )
      return

    setBusyId(connection.id)
    const res = await fetch(`/api/calendars/${connection.id}`, {
      method: 'DELETE',
    })
    if (res.ok) await load()
    else setError('Could not disconnect that calendar.')
    setBusyId(null)
  }

  return (
    <section>
      <h3>Calendars</h3>

      {error && (
        <p className="field-warning" role="alert">
          {error}
        </p>
      )}

      {notice && (
        <p className="field-hint" role="status">
          {notice}
        </p>
      )}

      {connections && connections.length > 0 && (
        <ul className="connection-list">
          {connections.map((connection) => (
            <li key={connection.id}>
              <div className="connection-head">
                <strong>{connection.account_email ?? 'Google Calendar'}</strong>
                {!connection.healthy && (
                  <span className="tag warn">Needs reconnecting</span>
                )}
                <span className="tag">
                  {connection.last_synced_at
                    ? `Synced ${new Date(
                        connection.last_synced_at,
                      ).toLocaleString()}`
                    : 'Not synced yet'}
                </span>
              </div>

              {connection.last_sync_error && (
                <p className="field-warning">{connection.last_sync_error}</p>
              )}

              {connection.calendars.length === 0 ? (
                <p className="field-hint">
                  No calendars found yet — sync to load them.
                </p>
              ) : (
                <ul className="calendar-list">
                  {connection.calendars.map((calendar) => (
                    <li key={calendar.id}>
                      <label className="calendar-check">
                        <input
                          type="checkbox"
                          checked={calendar.selected}
                          disabled={busyId === connection.id}
                          onChange={(e) =>
                            void updateCalendar(connection, calendar, {
                              selected: e.target.checked,
                            })
                          }
                        />
                        <span
                          className="calendar-dot"
                          style={{ background: calendar.color ?? 'var(--ink-3)' }}
                          aria-hidden="true"
                        />
                        <span className="calendar-name">{calendar.name}</span>
                        {calendar.is_primary && (
                          <span className="tag">Primary</span>
                        )}
                      </label>

                      <select
                        className="calendar-kind"
                        value={calendar.kind}
                        disabled={busyId === connection.id || !calendar.selected}
                        aria-label={`How to read ${calendar.name}`}
                        onChange={(e) =>
                          void updateCalendar(connection, calendar, {
                            kind: e.target.value as CalendarKind,
                          })
                        }
                      >
                        {KINDS.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>

                      {calendar.last_sync_error && (
                        <p className="field-warning">
                          {calendar.last_sync_error}
                        </p>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              <div className="actions">
                <button
                  className="button quiet"
                  disabled={busyId === connection.id}
                  onClick={() => void resync(connection)}
                >
                  {busyId === connection.id ? 'Syncing…' : 'Sync now'}
                </button>
                <button
                  className="button danger quiet"
                  disabled={busyId === connection.id}
                  onClick={() => void remove(connection)}
                >
                  Disconnect
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {connections && connections.length === 0 && (
        <p className="field-hint">
          No calendars connected yet. Connecting one imports your existing
          events so ScheduleAssist can schedule around them.
        </p>
      )}

      <div className="field">
        <label id="kind-label">What kind of calendar is this?</label>
        <div className="choices" role="group" aria-labelledby="kind-label">
          {KINDS.map((option) => (
            <button
              key={option.id}
              type="button"
              className="choice"
              aria-pressed={kind === option.id}
              onClick={() => setKind(option.id)}
            >
              {option.label}
              <small>{option.hint}</small>
            </button>
          ))}
        </div>
        <div className="actions">
          <button className="button" onClick={connect}>
            Connect a Google calendar
          </button>
        </div>
      </div>
    </section>
  )
}
