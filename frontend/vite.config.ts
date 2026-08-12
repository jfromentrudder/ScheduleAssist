import react from '@vitejs/plugin-react'
// From vitest/config rather than vite: it is the same defineConfig widened to
// type the `test` block below.
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Forward /api requests to the FastAPI backend during development
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    // jsdom rather than a real browser: everything under test here is either
    // pure date/layout maths or a component's rendered output and handlers.
    // Driving a real browser is a separate job, and Google blocks automating
    // its consent screen anyway — see the note in README.
    environment: 'jsdom',
    globals: false, // Imports are explicit, so `tsc -b` checks them like any other.
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // The grid renders in the *user's* zone, which is only meaningfully
    // different from the browser's if the browser is not in UTC. Pinning a
    // zone with a DST rule keeps those tests honest wherever they run —
    // including CI, which is UTC.
    env: { TZ: 'America/Los_Angeles' },
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/test/**', 'src/main.tsx'],
    },
  },
})
