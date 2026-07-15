import { useEffect, useState } from 'react'
import './App.css'

type Me = { id: number; email: string; display_name: string | null }

function App() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const authError = new URLSearchParams(window.location.search).has('auth_error')

  useEffect(() => {
    fetch('/api/auth/me')
      .then((res) => (res.ok ? res.json() : null))
      .then(setMe)
      .catch(() => setMe(null))
      .finally(() => setLoading(false))
  }, [])

  return (
    <section id="center">
      <div>
        <h1>ScheduleAssist</h1>
        <p>A smart scheduler for bad schedulers.</p>

        {loading ? (
          <p>Loading…</p>
        ) : me ? (
          <p>
            Signed in as <strong>{me.display_name ?? me.email}</strong>{' '}
            (<code>{me.email}</code>)
          </p>
        ) : (
          <>
            {authError && <p role="alert">Sign-in failed or was cancelled — try again.</p>}
            <a className="counter" href="/api/auth/google/login">
              Sign in with Google
            </a>
          </>
        )}
      </div>
    </section>
  )
}

export default App
