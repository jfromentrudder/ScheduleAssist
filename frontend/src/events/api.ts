/** Client for /api/events — creating and correcting events. */

import type {
  Availability,
  EventType,
  ScheduleEvent,
} from '../schedule/types'

export type EventDraft = {
  title: string
  description?: string | null
  event_type: EventType
  availability?: Availability
  starts_at?: string | null
  ends_at?: string | null
  due_at?: string | null
  expected_prep_minutes?: number | null
  type_locked?: boolean
}

async function send(
  url: string,
  method: string,
  body?: unknown,
): Promise<ScheduleEvent> {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    // The API explains impossible shapes ("a deadline needs a due date")
    // rather than leaving the constraint to fail; surface that wording.
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? `Request failed (${res.status})`)
  }
  return res.json()
}

export function createEvent(draft: EventDraft) {
  return send('/api/events', 'POST', draft)
}

export function updateEvent(id: number, draft: Partial<EventDraft>) {
  return send(`/api/events/${id}`, 'PATCH', draft)
}

export async function deleteEvent(id: number): Promise<void> {
  const res = await fetch(`/api/events/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    const detail = await res.json().catch(() => null)
    throw new Error(detail?.detail ?? 'Could not delete that event.')
  }
}

/** ISO instant to the "YYYY-MM-DDTHH:mm" a datetime-local input wants.
 *
 * Done by hand rather than with toISOString, which would render the value in
 * UTC and show the user a time they never entered. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}

/** The inverse: a local input value back to an ISO instant. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}
