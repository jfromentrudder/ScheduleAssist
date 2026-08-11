/** Connect and manage calendar accounts (issue #7).
 *
 * Connecting leaves the app entirely — the browser goes to Google's consent
 * screen and comes back to /account with a query flag — so this component
 * reads that flag on mount rather than awaiting a promise. */

import { useCallback, useEffect, useState } from 'react'

export type CalendarKind = 'school' | 'work' | 'personal'

export type Connection = {
  id: number
  provider: string
  account_email: string | null
  kind: CalendarKind
  created_at: string
  last_synced_at: string | null
  last_sync_error: string | null
  /** False once the grant is no longer refreshable; needs reconnecting. */
  healthy: boolean
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

  async function changeKind(id: number, next: CalendarKind) {
    setBusyId(id)
    const res = await fetch(`/api/calendars/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: next }),
    })
    if (res.ok) await load()
    else setError('Could not update that calendar.')
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

      {connections && connections.length > 0 && (
        <ul className="connection-list">
          {connections.map((connection) => (
            <li key={connection.id}>
              <div className="connection-head">
                <strong>{connection.account_email ?? 'Google Calendar'}</strong>
                {!connection.healthy && (
                  <span className="tag warn">Needs reconnecting</span>
                )}
              </div>

              <div className="choices" role="group" aria-label="Calendar type">
                {KINDS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="choice"
                    aria-pressed={connection.kind === option.id}
                    disabled={busyId === connection.id}
                    onClick={() => void changeKind(connection.id, option.id)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div className="actions">
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
