import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'
import { APPEARANCES, THEMES } from '../theme/constants'
import { useTheme } from '../theme/useTheme'

type AccountDetails = {
  id: number
  email: string
  display_name: string | null
  created_at: string
  providers: string[]
  schedule_horizon_days: number
  /** Non-null only at the extremes of the allowed range. */
  schedule_horizon_warning: string | null
}

// Mirrors MIN/MAX_HORIZON_DAYS in backend/app/scheduler.py, which are also the
// bounds of the CHECK constraint on the column.
const MIN_HORIZON_DAYS = 1
const MAX_HORIZON_DAYS = 21

/** Live preview of a theme's category colours, rendered in the current mode. */
function ThemeSwatches({ themeId }: { themeId: string }) {
  const { mode } = useTheme()
  return (
    <span className="swatch-row" data-theme={themeId} data-mode={mode} aria-hidden="true">
      <i style={{ background: 'var(--imp)' }} />
      <i style={{ background: 'var(--man)' }} />
      <i style={{ background: 'var(--per-bg)', border: '1px dashed var(--per)' }} />
      <i style={{ background: 'var(--due)' }} />
    </span>
  )
}

export function Account() {
  const { refresh, signOut } = useAuth()
  const { theme, appearance, setTheme, setAppearance } = useTheme()
  const navigate = useNavigate()

  const [account, setAccount] = useState<AccountDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/api/account')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('load failed'))))
      .then(setAccount)
      .catch(() => setError('Could not load your account details.'))
  }, [])

  async function handleHorizonChange(days: number) {
    // Optimistic: the slider must track the thumb, not the network. The
    // response carries the authoritative value and warning.
    setAccount((current) =>
      current ? { ...current, schedule_horizon_days: days } : current,
    )
    const res = await fetch('/api/account', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ schedule_horizon_days: days }),
    })
    if (res.ok) setAccount(await res.json())
    else setError('Could not save your planning horizon.')
  }

  async function handleSignOut() {
    setBusy(true)
    await signOut()
    navigate('/signin', { replace: true })
  }

  async function handleDelete() {
    if (!confirm('Delete your account? This erases your data and cannot be undone.')) return

    setBusy(true)
    const res = await fetch('/api/account', { method: 'DELETE' })
    if (!res.ok) {
      setError('Could not delete your account. Please try again.')
      setBusy(false)
      return
    }
    // The server already cleared the session cookie; sync client state to match.
    await refresh()
    navigate('/signin', { replace: true })
  }

  return (
    <div className="panel">
      <h1 style={{ fontSize: 32, margin: 0 }}>Account</h1>

      {error && <p role="alert">{error}</p>}

      <section>
        <h3>Profile</h3>
        {account && (
          <dl>
            <dt>Name</dt>
            <dd>{account.display_name ?? '—'}</dd>
            <dt>Email</dt>
            <dd>{account.email}</dd>
            <dt>Signs in with</dt>
            <dd>{account.providers.join(', ') || '—'}</dd>
            <dt>Member since</dt>
            <dd>{new Date(account.created_at).toLocaleDateString()}</dd>
          </dl>
        )}
      </section>

      <section>
        <h3>Appearance</h3>

        <div className="field">
          <label id="theme-label">Theme</label>
          <div className="choices" role="group" aria-labelledby="theme-label">
            {THEMES.map((option) => (
              <button
                key={option.id}
                type="button"
                className="choice"
                aria-pressed={theme === option.id}
                onClick={() => setTheme(option.id)}
              >
                <ThemeSwatches themeId={option.id} />
                {option.label}
                <small>{option.hint}</small>
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label id="appearance-label">Light or dark</label>
          <div className="choices" role="group" aria-labelledby="appearance-label">
            {APPEARANCES.map((option) => (
              <button
                key={option.id}
                type="button"
                className="choice"
                aria-pressed={appearance === option.id}
                onClick={() => setAppearance(option.id)}
              >
                {option.label}
                {option.hint && <small>{option.hint}</small>}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section>
        <h3>Scheduling</h3>

        {account && (
          <div className="field">
            <label htmlFor="horizon">Planning horizon</label>
            <p className="field-hint">
              How far ahead your schedule is settled. Work periods inside the
              horizon stay put when new events arrive; beyond it they are
              rearranged to fit.
            </p>
            <div className="slider-row">
              <input
                id="horizon"
                type="range"
                min={MIN_HORIZON_DAYS}
                max={MAX_HORIZON_DAYS}
                value={account.schedule_horizon_days}
                onChange={(e) => void handleHorizonChange(Number(e.target.value))}
                aria-describedby="horizon-value"
              />
              <output id="horizon-value" htmlFor="horizon">
                {account.schedule_horizon_days}
                {account.schedule_horizon_days === 1 ? ' day' : ' days'}
              </output>
            </div>
            {account.schedule_horizon_warning && (
              <p className="field-warning" role="status">
                {account.schedule_horizon_warning}
              </p>
            )}
          </div>
        )}
      </section>

      <section>
        <h3>Session</h3>
        <div className="actions">
          <button className="button quiet" onClick={handleSignOut} disabled={busy}>
            Sign out
          </button>
          <button className="button danger" onClick={handleDelete} disabled={busy}>
            Delete account
          </button>
        </div>
      </section>
    </div>
  )
}
