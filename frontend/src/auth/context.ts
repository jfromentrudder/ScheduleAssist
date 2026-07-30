import { createContext } from 'react'

export type User = { id: number; email: string; display_name: string | null }

export type AuthState = {
  user: User | null
  /** True until the first /me probe settles, so guards don't redirect early. */
  loading: boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)
