/** Client for /api/periods — removing a generated block.
 *
 * Deleting a period inside the commitment horizon is a two-step call, the same
 * shape as generation: the first attempt is refused with the reason, and the
 * client repeats it once the user has seen the warning. The server derives
 * "settled" from the horizon rather than trusting the client, so a page open
 * since yesterday cannot delete something that has settled since. */

export class SettledPeriod extends Error {}

export async function deletePeriod(id: number, confirm = false): Promise<void> {
  const query = confirm ? '?confirm=true' : ''
  const res = await fetch(`/api/periods/${id}${query}`, { method: 'DELETE' })
  if (res.ok) return

  const detail = await res.json().catch(() => null)
  const message =
    typeof detail?.detail === 'string'
      ? detail.detail
      : 'Could not delete that period.'
  // 409 is only ever the settled case on this endpoint.
  if (res.status === 409) throw new SettledPeriod(message)
  throw new Error(message)
}
