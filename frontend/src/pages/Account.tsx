/** Who you are: the details of the account itself.
 *
 * Deliberately separate from Settings. Nothing here changes how the app
 * behaves — it is identity and the one irreversible action — so it does not
 * belong on the same page as a dozen controls people adjust casually. */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

type Profile = {
  id: number
  email: string
  display_name: string | null
  created_at: string
  providers: string[]
}

export function Account() {
  const { refresh } = useAuth()
  const navigate = useNavigate()

  const [account, setAccount] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/api/account')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('load failed'))))
      .then(setAccount)
      .catch(() => setError('Could not load your account details.'))
  }, [])

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
        <p className="field-hint">
          Your name and email come from the account you sign in with, so they
          are changed there rather than here.
        </p>
      </section>

      <section>
        <h3>Delete account</h3>
        <p className="field-hint">
          Removes your schedule, your events and every connected calendar. This
          cannot be undone.
        </p>
        <div className="actions">
          <button className="button danger" onClick={handleDelete} disabled={busy}>
            Delete account
          </button>
        </div>
      </section>
    </div>
  )
}
