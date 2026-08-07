/** Client for POST /api/schedule/generate.
 *
 * The endpoint is deliberately two-phase: the first call tries to fit new work
 * into the gaps left by the settled part of the schedule, and if that falls
 * short it returns the shortfall *without writing anything*. The user picks a
 * remedy and we call again with their answer, which always commits. */

export type Unmet = {
  event_id: number
  periods_needed: number
  periods_allocated: number
  reason: string
}

export type TimeWindow = {
  starts_at: string
  ends_at: string
}

export type GenerateRequest = {
  strategy?: 'additive' | 'rebuild'
  extra_windows?: TimeWindow[]
  accept_unmet?: boolean
}

export type Committed = {
  committed: true
  periods_created: number
  periods_kept: number
  unmet: Unmet[]
}

export type NeedsDecision = {
  committed: false
  unmet: Unmet[]
  options: {
    /** `resolves` is false when rebuilding would not actually help — the UI
     *  must not offer to disrupt a settled week for no gain. */
    rebuild: { resolves: boolean; periods_moved: number }
    extend_hours: { available: boolean }
    accept_unmet: { available: boolean }
  }
}

export type GenerateResponse = Committed | NeedsDecision

export async function generateSchedule(
  body: GenerateRequest = {},
): Promise<GenerateResponse> {
  const res = await fetch('/api/schedule/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Generate failed (${res.status})`)
  return res.json()
}

/** Combines a local date and time into the ISO instant the API expects. */
export function toInstant(date: string, time: string): string {
  return new Date(`${date}T${time}`).toISOString()
}
