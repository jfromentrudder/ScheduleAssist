/** Everything that changes how ScheduleAssist behaves.
 *
 * Appearance, which calendars it reads, and the preferences the generator works
 * from. Split out from Account because these are the controls people actually
 * come back to adjust, and they were previously buried under profile details
 * they never need to look at twice. */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { Calendars } from '../calendars/Calendars'
import { Scheduling } from '../settings/Scheduling'
import type { SchedulingPrefs } from '../settings/Scheduling'
import { APPEARANCES, THEMES } from '../theme/constants'
import { useTheme } from '../theme/useTheme'

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

export function Settings() {
  const { theme, appearance, setTheme, setAppearance } = useTheme()
  const navigate = useNavigate()

  const [prefs, setPrefs] = useState<SchedulingPrefs | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // True once a preference changes that the current schedule was not built with.
  const [stale, setStale] = useState(false)

  useEffect(() => {
    fetch('/api/account')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('load failed'))))
      .then(setPrefs)
      .catch(() => setError('Could not load your settings.'))
  }, [])

  async function savePrefs(change: Partial<SchedulingPrefs>) {
    // Optimistic: a slider must track the thumb, not the network. The response
    // carries the authoritative values and any warning.
    setPrefs((current) => (current ? { ...current, ...change } : current))
    setError(null)
    setSaving(true)

    const res = await fetch('/api/account', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(change),
    })

    if (res.ok) {
      const saved = await res.json()
      setPrefs(saved)
      // These preferences decide what a generated schedule looks like, so the
      // existing one no longer reflects them.
      if (saved.schedule_stale) setStale(true)
    } else {
      const detail = await res.json().catch(() => null)
      setError(
        typeof detail?.detail === 'string'
          ? detail.detail
          : 'Could not save that setting.',
      )
      // Roll the optimistic change back to whatever the server still holds.
      const fresh = await fetch('/api/account')
      if (fresh.ok) setPrefs(await fresh.json())
    }
    setSaving(false)
  }

  async function regenerate() {
    setSaving(true)
    const res = await fetch('/api/schedule/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // A full rebuild, not the additive default. The periods that break the
      // new settings are usually inside the horizon, and an additive pass
      // protects exactly those — leaving the schedule visibly wrong.
      body: JSON.stringify({ strategy: 'rebuild' }),
    })
    setSaving(false)
    if (!res.ok) {
      setError('Could not rebuild your schedule.')
      return
    }
    setStale(false)
    // A shortfall needs the choice dialog, which lives on the schedule page.
    if (!(await res.json()).committed) navigate('/')
  }

  return (
    <div className="panel">
      <h1 style={{ fontSize: 32, margin: 0 }}>Settings</h1>

      {error && <p role="alert">{error}</p>}

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

      <Calendars />

      {prefs && <Scheduling prefs={prefs} onSave={savePrefs} busy={saving} />}

      {stale && (
        <div className="stale-banner" role="status">
          <span>
            Your schedule was built with the old settings. Rebuilding moves
            every period to match them, including ones already settled inside
            your horizon.
          </span>
          <button
            className="button"
            disabled={saving}
            onClick={() => void regenerate()}
          >
            {saving ? 'Rebuilding…' : 'Rebuild schedule'}
          </button>
        </div>
      )}
    </div>
  )
}
