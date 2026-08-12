/** Tests for the period-deletion client.
 *
 * This encodes half of a two-phase contract: the server refuses to delete a
 * settled period until the caller repeats the request with `confirm`, and it
 * distinguishes that refusal from any other failure by status. Getting the
 * distinction wrong would either lose the warning or turn a real error into a
 * confirmation prompt. */

import { afterEach, describe, expect, it, vi } from 'vitest'

import { SettledPeriod, deletePeriod } from './periods'

/** A fetch that answers once with the given status and JSON body. */
function respond(status: number, body?: unknown) {
  const fetchMock = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (body === undefined) throw new Error('no body')
      return body
    },
  }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('a period that is free to go', () => {
  it('resolves on success', async () => {
    respond(204)

    await expect(deletePeriod(10)).resolves.toBeUndefined()
  })

  it('asks without confirmation the first time', async () => {
    const fetchMock = respond(204)

    await deletePeriod(10)

    expect(fetchMock).toHaveBeenCalledWith('/api/periods/10', {
      method: 'DELETE',
    })
  })
})

describe('a settled period', () => {
  const detail =
    'That period is settled — it sits inside your planning horizon.'

  it('is reported as its own kind of failure, not a generic one', async () => {
    respond(409, { detail })

    await expect(deletePeriod(10)).rejects.toBeInstanceOf(SettledPeriod)
  })

  it('carries the server\'s own wording, which the dialog shows', async () => {
    respond(409, { detail })

    await expect(deletePeriod(10)).rejects.toThrow(detail)
  })

  it('goes through once confirmed', async () => {
    const fetchMock = respond(204)

    await deletePeriod(10, true)

    expect(fetchMock).toHaveBeenCalledWith('/api/periods/10?confirm=true', {
      method: 'DELETE',
    })
  })
})

describe('anything else going wrong', () => {
  it('is a plain error, so the caller does not offer to confirm it', async () => {
    respond(404, { detail: 'Period not found' })

    const failure = await deletePeriod(10).catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(Error)
    expect(failure).not.toBeInstanceOf(SettledPeriod)
    expect((failure as Error).message).toBe('Period not found')
  })

  it('falls back to readable wording when there is no JSON to read', async () => {
    respond(500)

    await expect(deletePeriod(10)).rejects.toThrow(
      'Could not delete that period.',
    )
  })

  it('falls back when the body is JSON but carries no detail', async () => {
    respond(500, { oops: true })

    await expect(deletePeriod(10)).rejects.toThrow(
      'Could not delete that period.',
    )
  })
})
