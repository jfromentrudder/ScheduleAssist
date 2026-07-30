import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './useAuth'

/**
 * Route guard: renders nested routes only when signed in, otherwise sends the
 * visitor to /signin, remembering where they were headed.
 */
export function RequireAuth() {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <p>Loading…</p>
  if (!user) return <Navigate to="/signin" replace state={{ from: location }} />
  return <Outlet />
}
