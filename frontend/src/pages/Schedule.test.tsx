/** Tests for the schedule page's own job: deciding what range is on screen.
 *
 * The grids are tested separately. What lives here is the wiring — which span
 * is active, what date range that asks the API for, what the previous/next
 * buttons step by, and that the choice is remembered. None of it had any
 * coverage before, and every one of those is easy to get subtly wrong. */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { Schedule } from './Schedule'

// The page reads the user only for their timezone. UTC keeps the expected
// ranges readable; the zone handling itself is tested in week.test.ts.
vi.mock('../auth/useAuth', () => ({
  useAuth: () => ({
    user: {
      id: 1,
      email: 'test@example.com',
      display_name: 'Test',
      theme: 'ember',
      appearance: 'system',
      timezone: 'UTC',
    },
    loading: false,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}))

const PREFERENCES = {
  workdays: [0, 1, 2, 3, 4],
  day_start: '09:00:00',
  day_end: '17:00:00',
  period_minutes: 50,
  timezone: 'UTC',
  schedule_horizon_days: 5,
}

/** Every request the page makes, so the range asked for can be asserted. */
let requests: string[] = []

function mockFetch() {
  requests = []
  const fetchMock = vi.fn(async (url: string) => {
    requests.push(url)
    return {
      ok: true,
      status: 200,
      json: async () => ({
        start: '',
        end: '',
        view: 'generated',
        preferences: PREFERENCES,
        horizon_ends_at: null,
        events: [],
        periods: [],
      }),
    }
  })
  vi.stubGlobal('fetch', fetchMock)
}

/** The start/end the page last asked for, as ISO strings. */
function lastRange(): { start: string; end: string } {
  const params = new URLSearchParams(requests.at(-1)!.split('?')[1])
  return { start: params.get('start')!, end: params.get('end')! }
}

const spanButton = (name: 'Day' | 'Week' | 'Month') =>
  screen.getByRole('button', { name })

beforeEach(() => {
  // Wednesday 12 August 2026, 12:00 UTC. Every expectation below is relative
  // to this, so the suite does not drift with the real calendar.
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date('2026-08-12T12:00:00Z'))
  localStorage.clear()
  mockFetch()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function draw() {
  const result = render(<Schedule />)
  await waitFor(() => expect(requests.length).toBeGreaterThan(0))
  return result
}

// --- Defaults -----------------------------------------------------------

describe('opening the page', () => {
  it('starts on the week', async () => {
    await draw()

    expect(spanButton('Week')).toHaveAttribute('aria-pressed', 'true')
  })

  it('asks for the Monday-to-Monday week containing today', async () => {
    await draw()

    // Wednesday the 12th sits in the week beginning Monday the 10th.
    expect(lastRange()).toEqual({
      start: '2026-08-10T00:00:00.000Z',
      end: '2026-08-17T00:00:00.000Z',
    })
  })

  it('heads the view with the week it is showing', async () => {
    await draw()

    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
      'Aug 10 – 16, 2026',
    )
  })
})

// --- Switching span -----------------------------------------------------

describe('switching to a day', () => {
  it('asks for a single day', async () => {
    await draw()

    await userEvent.click(spanButton('Day'))

    await waitFor(() =>
      expect(lastRange()).toEqual({
        start: '2026-08-12T00:00:00.000Z',
        end: '2026-08-13T00:00:00.000Z',
      }),
    )
  })

  it('names the day, weekday included', async () => {
    await draw()

    await userEvent.click(spanButton('Day'))

    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
        'Wed, Aug 12, 2026',
      ),
    )
  })
})

describe('switching to a month', () => {
  it('asks for the whole six-week grid, so no cell is blank', async () => {
    await draw()

    await userEvent.click(spanButton('Month'))

    // August 2026 starts on a Saturday, so the grid opens Monday 27 July and
    // runs 42 days to Monday 7 September.
    await waitFor(() =>
      expect(lastRange()).toEqual({
        start: '2026-07-27T00:00:00.000Z',
        end: '2026-09-07T00:00:00.000Z',
      }),
    )
  })

  it('titles it with the month itself, not the grid start', async () => {
    await draw()

    await userEvent.click(spanButton('Month'))

    // The grid begins in July; the heading must still say August.
    await waitFor(() =>
      expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
        'August 2026',
      ),
    )
  })
})

// --- Navigation steps by the active span --------------------------------

describe('previous and next', () => {
  it('steps a week in week view', async () => {
    await draw()

    await userEvent.click(screen.getByRole('button', { name: 'Next week' }))

    await waitFor(() => expect(lastRange().start).toBe('2026-08-17T00:00:00.000Z'))
  })

  it('steps a day in day view', async () => {
    await draw()
    await userEvent.click(spanButton('Day'))

    await userEvent.click(screen.getByRole('button', { name: 'Next day' }))

    await waitFor(() => expect(lastRange().start).toBe('2026-08-13T00:00:00.000Z'))
  })

  it('steps a month in month view', async () => {
    await draw()
    await userEvent.click(spanButton('Month'))

    await userEvent.click(screen.getByRole('button', { name: 'Next month' }))

    // September 2026 begins on a Tuesday, so its grid opens Monday 31 August.
    await waitFor(() => expect(lastRange().start).toBe('2026-08-31T00:00:00.000Z'))
  })

  it('goes backwards too', async () => {
    await draw()

    await userEvent.click(screen.getByRole('button', { name: 'Previous week' }))

    await waitFor(() => expect(lastRange().start).toBe('2026-08-03T00:00:00.000Z'))
  })

  it('offers a way back to today once you have moved', async () => {
    await draw()
    expect(screen.queryByRole('button', { name: 'Today' })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Next week' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Today' }))

    await waitFor(() => expect(lastRange().start).toBe('2026-08-10T00:00:00.000Z'))
  })

  it('returns to today when the span changes', async () => {
    await draw()
    await userEvent.click(screen.getByRole('button', { name: 'Next week' }))

    await userEvent.click(spanButton('Day'))

    // Deliberate: switching span means "show me now at this zoom" rather than
    // carrying a date across three different units.
    await waitFor(() => expect(lastRange().start).toBe('2026-08-12T00:00:00.000Z'))
  })
})

// --- Remembering the choice ---------------------------------------------

describe('remembering the span', () => {
  it('stores it per browser', async () => {
    await draw()

    await userEvent.click(spanButton('Month'))

    await waitFor(() => expect(localStorage.getItem('sa-span')).toBe('month'))
  })

  it('opens on the stored span next time', async () => {
    localStorage.setItem('sa-span', 'day')

    await draw()

    expect(spanButton('Day')).toHaveAttribute('aria-pressed', 'true')
  })

  it('ignores a stored value it does not recognise', async () => {
    localStorage.setItem('sa-span', 'fortnight')

    await draw()

    expect(spanButton('Week')).toHaveAttribute('aria-pressed', 'true')
  })
})

// --- The two switches are independent -----------------------------------

describe('span and view are separate axes', () => {
  it('keeps the span when the view changes', async () => {
    await draw()
    await userEvent.click(spanButton('Day'))

    await userEvent.click(screen.getByRole('button', { name: 'Calendar' }))

    expect(spanButton('Day')).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(lastRange().start).toBe('2026-08-12T00:00:00.000Z'))
  })

  it('sends the view along with the range', async () => {
    await draw()

    await userEvent.click(screen.getByRole('button', { name: 'Calendar' }))

    await waitFor(() => expect(requests.at(-1)).toContain('view=calendar'))
  })
})
