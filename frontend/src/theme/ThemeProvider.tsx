import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { useAuth } from '../auth/useAuth'
import {
  DEFAULT_APPEARANCE,
  DEFAULT_THEME,
  STORAGE_KEYS,
  isAppearanceId,
  isThemeId,
} from './constants'
import type { AppearanceId, ThemeId } from './constants'
import { ThemeContext } from './context'

function readStored<T>(key: string, guard: (v: unknown) => v is T, fallback: T): T {
  try {
    const stored = localStorage.getItem(key)
    return guard(stored) ? stored : fallback
  } catch {
    // Private browsing can throw on localStorage access.
    return fallback
  }
}

function store(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // Preference still applies for this session; it just won't persist locally.
  }
}

const darkQuery = () => window.matchMedia('(prefers-color-scheme: dark)')

export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()

  // Seeded from localStorage so a reload paints the right theme immediately;
  // the signed-in user's saved values overwrite these once /me resolves.
  const [theme, setThemeState] = useState<ThemeId>(() =>
    readStored(STORAGE_KEYS.theme, isThemeId, DEFAULT_THEME),
  )
  const [appearance, setAppearanceState] = useState<AppearanceId>(() =>
    readStored(STORAGE_KEYS.appearance, isAppearanceId, DEFAULT_APPEARANCE),
  )
  const [systemDark, setSystemDark] = useState(() => darkQuery().matches)

  // Track the browser preference so "system" stays live rather than being
  // sampled once at load.
  useEffect(() => {
    const query = darkQuery()
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  // Adopt the server's saved preference on sign-in.
  useEffect(() => {
    if (!user) return
    if (isThemeId(user.theme)) {
      setThemeState(user.theme)
      store(STORAGE_KEYS.theme, user.theme)
    }
    if (isAppearanceId(user.appearance)) {
      setAppearanceState(user.appearance)
      store(STORAGE_KEYS.appearance, user.appearance)
    }
  }, [user])

  const mode: 'light' | 'dark' =
    appearance === 'system' ? (systemDark ? 'dark' : 'light') : appearance

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.dataset.mode = mode
    // Lets form controls and scrollbars match without extra styling.
    root.style.colorScheme = mode
  }, [theme, mode])

  /** Applies immediately, then persists. The UI never waits on the network. */
  const save = useCallback(
    (body: { theme?: ThemeId; appearance?: AppearanceId }) => {
      void fetch('/api/account', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).catch(() => {
        // Local preference still holds; it will re-sync on the next save.
      })
    },
    [],
  )

  const setTheme = useCallback(
    (next: ThemeId) => {
      setThemeState(next)
      store(STORAGE_KEYS.theme, next)
      save({ theme: next })
    },
    [save],
  )

  const setAppearance = useCallback(
    (next: AppearanceId) => {
      setAppearanceState(next)
      store(STORAGE_KEYS.appearance, next)
      save({ appearance: next })
    },
    [save],
  )

  const value = useMemo(
    () => ({ theme, appearance, mode, setTheme, setAppearance }),
    [theme, appearance, mode, setTheme, setAppearance],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
