import { Link } from 'react-router-dom'

import { useAuth } from '../auth/useAuth'

export function Home() {
  const { user } = useAuth()

  return (
    <section id="center">
      <div>
        <h1>ScheduleAssist</h1>
        <p>
          Signed in as <strong>{user?.display_name ?? user?.email}</strong>
        </p>
        <p>Your schedule will live here once the scheduling engine lands.</p>
        <Link className="counter" to="/account">
          Account
        </Link>
      </div>
    </section>
  )
}
