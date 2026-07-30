import { useContext } from 'react'

import { ThemeContext } from './context'
import type { ThemeState } from './context'

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>')
  return ctx
}
