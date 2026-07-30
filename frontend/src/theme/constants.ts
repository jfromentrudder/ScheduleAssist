export const THEMES = [
  { id: 'ember', label: 'Ember', hint: 'Cool slate, amber work periods' },
  { id: 'tide', label: 'Tide', hint: 'Soft teal, low contrast' },
  { id: 'meridian', label: 'Meridian', hint: 'Saturated and high contrast' },
  { id: 'graphite', label: 'Graphite', hint: 'Neutral greys, blue accent' },
  { id: 'daylight', label: 'Daylight', hint: 'Warm greys, moss accent' },
  { id: 'signal', label: 'Signal', hint: 'Near-monochrome, green periods' },
] as const

export const APPEARANCES = [
  { id: 'system', label: 'System', hint: 'Follow your browser' },
  { id: 'light', label: 'Light', hint: '' },
  { id: 'dark', label: 'Dark', hint: '' },
] as const

export type ThemeId = (typeof THEMES)[number]['id']
export type AppearanceId = (typeof APPEARANCES)[number]['id']

export const DEFAULT_THEME: ThemeId = 'ember'
export const DEFAULT_APPEARANCE: AppearanceId = 'system'

/** Mirrors the keys the pre-paint script in index.html writes. */
export const STORAGE_KEYS = { theme: 'sa-theme', appearance: 'sa-appearance' }

export function isThemeId(value: unknown): value is ThemeId {
  return THEMES.some((t) => t.id === value)
}

export function isAppearanceId(value: unknown): value is AppearanceId {
  return APPEARANCES.some((a) => a.id === value)
}
