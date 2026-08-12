/** Test environment shims and matchers.
 *
 * jsdom implements the DOM but not the browser around it, so the few browser
 * APIs this app depends on are stubbed here rather than in each test. */

import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// Vitest does not unmount between tests on its own, and a left-over tree makes
// the *next* test's queries ambiguous in ways that read as unrelated failures.
afterEach(cleanup)

// ThemeProvider resolves "system" through matchMedia, which jsdom omits
// entirely. Defaults to light so a component's snapshot does not depend on the
// machine running it.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  })) as unknown as typeof window.matchMedia
}

// jsdom throws "not implemented" for these. Tests that care about them assert
// on the spy; the rest just need the call not to explode.
window.confirm = vi.fn(() => true)
window.alert = vi.fn()
