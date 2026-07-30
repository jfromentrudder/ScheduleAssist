import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

type LocationState = { from?: { pathname: string } }

export function SignIn() {
  const { user, loading } = useAuth()
  const location = useLocation()
  const authError = new URLSearchParams(location.search).has('auth_error')

  if (loading) return <p>Loading…</p>
  if (user) {
    // Send them back to the page the guard bounced them off of.
    const from = (location.state as LocationState | null)?.from?.pathname ?? '/'
    return <Navigate to={from} replace />
  }

  return (
    <section id="center">
      <div>
        <h1>ScheduleAssist</h1>
        <p>A smart scheduler for bad schedulers.</p>

        {authError && <p role="alert">Sign-in failed or was cancelled — try again.</p>}
        <a className="counter" href="/api/auth/google/login">
          Sign in with Google
        </a>
      </div>
    </section>
  )
}
