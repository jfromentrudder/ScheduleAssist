import { createContext } from 'react'

import type { AppearanceId, ThemeId } from './constants'

export type ThemeState = {
  theme: ThemeId
  appearance: AppearanceId
  /** What `appearance` resolves to right now — "system" becomes light or dark. */
  mode: 'light' | 'dark'
  setTheme: (theme: ThemeId) => void
  setAppearance: (appearance: AppearanceId) => void
}

export const ThemeContext = createContext<ThemeState | null>(null)
