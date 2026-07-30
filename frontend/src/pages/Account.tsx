import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

type Account = {
  id: number
  email: string
  display_name: string | null
  created_at: string
  providers: string[]
}

export function Account() {
  const { refresh, signOut } = useAuth()
  const navigate = useNavigate()
  const [account, setAccount] = useState<Account | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetch('/api/account')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error('load failed'))))
      .then(setAccount)
      .catch(() => setError('Could not load your account details.'))
  }, [])

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
    <section id="center">
      <div>
        <h1>Account</h1>

        {error && <p role="alert">{error}</p>}

        {account && (
          <dl>
            <dt>Name</dt>
            <dd>{account.display_name ?? '—'}</dd>
            <dt>Email</dt>
            <dd>
              <code>{account.email}</code>
            </dd>
            <dt>Signs in with</dt>
            <dd>{account.providers.join(', ') || '—'}</dd>
            <dt>Member since</dt>
            <dd>{new Date(account.created_at).toLocaleDateString()}</dd>
          </dl>
        )}

        <button className="counter" onClick={handleSignOut} disabled={busy}>
          Sign out
        </button>
        <button className="counter danger" onClick={handleDelete} disabled={busy}>
          Delete account
        </button>
        <p>
          <Link to="/">Back to schedule</Link>
        </p>
      </div>
    </section>
  )
}
