import { createContext } from 'react'

export type User = {
  id: number
  email: string
  display_name: string | null
  theme: string
  appearance: string
  /** IANA zone the schedule grid renders in, not necessarily the browser's. */
  timezone: string
}

export type AuthState = {
  user: User | null
  /** True until the first /me probe settles, so guards don't redirect early. */
  loading: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)
