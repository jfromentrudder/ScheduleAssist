/** Creating an event, and correcting one the app guessed wrong.
 *
 * The two jobs share a form because they are the same decisions: what is this,
 * when is it, and what should the schedule do about it. */

import { useState } from 'react'

import type {
  Availability,
  EventType,
  ScheduleEvent,
} from '../schedule/types'
import {
  createEvent,
  deleteEvent,
  fromLocalInput,
  toLocalInput,
  updateEvent,
} from './api'
import type { EventDraft } from './api'

type Props = {
  /** Absent when creating. */
  event: ScheduleEvent | null
  onClose: () => void
  onSaved: () => void
}

const AVAILABILITY: {
  id: Availability
  label: string
  hint: string
}[] = [
  { id: 'busy', label: 'Busy', hint: 'Work is scheduled around this' },
  { id: 'work_window', label: 'Time to work', hint: 'Work is scheduled inside it' },
  { id: 'free', label: 'Just a note', hint: 'Ignored when scheduling' },
]

function defaultStart(): string {
  const now = new Date()
  now.setMinutes(0, 0, 0)
  now.setHours(now.getHours() + 1)
  return toLocalInput(now.toISOString())
}

function plusHour(value: string): string {
  const date = new Date(value)
  date.setHours(date.getHours() + 1)
  return toLocalInput(date.toISOString())
}

export function EventEditor({ event, onClose, onSaved }: Props) {
  const creating = event === null

  const [title, setTitle] = useState(event?.title ?? '')
  const [description, setDescription] = useState(event?.description ?? '')
  const [type, setType] = useState<EventType>(event?.event_type ?? 'one_time')
  const [availability, setAvailability] = useState<Availability>(
    event?.availability ?? 'busy',
  )
  const [startsAt, setStartsAt] = useState(
    toLocalInput(event?.starts_at ?? null) || defaultStart(),
  )
  const [endsAt, setEndsAt] = useState(
    toLocalInput(event?.ends_at ?? null) || plusHour(defaultStart()),
  )
  const [dueAt, setDueAt] = useState(
    toLocalInput(event?.due_at ?? null) || defaultStart(),
  )
  const [prep, setPrep] = useState(
    event?.expected_prep_minutes ? String(event.expected_prep_minutes) : '',
  )

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isDeadline = type === 'deadline'
  const canDelete = !creating && event?.source === 'manual'

  async function save() {
    setBusy(true)
    setError(null)

    const draft: EventDraft = {
      title: title.trim() || 'Untitled',
      description: description.trim() || null,
      event_type: type,
      expected_prep_minutes: prep ? Number(prep) : null,
    }
    if (isDeadline) {
      draft.due_at = fromLocalInput(dueAt)
      draft.starts_at = null
      draft.ends_at = null
    } else {
      draft.starts_at = fromLocalInput(startsAt)
      draft.ends_at = fromLocalInput(endsAt)
      draft.due_at = null
      draft.availability = availability
    }

    try {
      if (creating) await createEvent(draft)
      else await updateEvent(event!.id, draft)
      onSaved()
    } catch (failure) {
      setError((failure as Error).message)
      setBusy(false)
    }
  }

  async function remove() {
    if (!confirm(`Delete "${event!.title}"?`)) return
    setBusy(true)
    setError(null)
    try {
      await deleteEvent(event!.id)
      onSaved()
    } catch (failure) {
      setError((failure as Error).message)
      setBusy(false)
    }
  }

  /** Hands an imported event back to inference on the next sync. */
  async function unlock() {
    setBusy(true)
    try {
      await updateEvent(event!.id, { type_locked: false })
      onSaved()
    } catch (failure) {
      setError((failure as Error).message)
      setBusy(false)
    }
  }

  return (
    <div className="modal-scrim" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="event-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="event-title">{creating ? 'Add an event' : 'Event details'}</h2>

        {error && (
          <p className="field-warning" role="alert">
            {error}
          </p>
        )}

        <div className="field">
          <label htmlFor="ev-title">Title</label>
          <input
            id="ev-title"
            className="text-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What is it?"
          />
        </div>

        <div className="field">
          <label id="ev-type-label">What kind of thing is this?</label>
          <div className="choices" role="group" aria-labelledby="ev-type-label">
            <button
              type="button"
              className="choice"
              aria-pressed={!isDeadline}
              onClick={() => setType('one_time')}
            >
              Event
              <small>Happens at a set time</small>
            </button>
            <button
              type="button"
              className="choice"
              aria-pressed={isDeadline}
              onClick={() => setType('deadline')}
            >
              Deadline
              <small>Work is due by then</small>
            </button>
          </div>
        </div>

        {isDeadline ? (
          <>
            <div className="field">
              <label htmlFor="ev-due">Due</label>
              <input
                id="ev-due"
                type="datetime-local"
                className="text-input"
                value={dueAt}
                onChange={(e) => setDueAt(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="ev-prep">How long will it take? (minutes)</label>
              <input
                id="ev-prep"
                type="number"
                min={1}
                step={15}
                className="text-input"
                value={prep}
                onChange={(e) => setPrep(e.target.value)}
                placeholder="Leave blank if you're not sure"
              />
            </div>
          </>
        ) : (
          <>
            <div className="window-picker">
              <label>
                Starts
                <input
                  type="datetime-local"
                  value={startsAt}
                  onChange={(e) => setStartsAt(e.target.value)}
                />
              </label>
              <label>
                Ends
                <input
                  type="datetime-local"
                  value={endsAt}
                  onChange={(e) => setEndsAt(e.target.value)}
                />
              </label>
            </div>

            <div className="field">
              <label id="ev-avail-label">What should the schedule do?</label>
              <div
                className="choices"
                role="group"
                aria-labelledby="ev-avail-label"
              >
                {AVAILABILITY.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="choice"
                    aria-pressed={availability === option.id}
                    onClick={() => setAvailability(option.id)}
                  >
                    {option.label}
                    <small>{option.hint}</small>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        <div className="field">
          <label htmlFor="ev-notes">Notes</label>
          <textarea
            id="ev-notes"
            className="text-input"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        {!creating && event!.source === 'imported' && event!.type_locked && (
          <p className="field-hint">
            You've customised this, so syncing won't change it back.{' '}
            <button className="text-button" disabled={busy} onClick={() => void unlock()}>
              Undo my changes
            </button>
          </p>
        )}

        <div className="modal-actions">
          <button className="button" disabled={busy} onClick={() => void save()}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          {canDelete && (
            <button
              className="button danger quiet"
              disabled={busy}
              onClick={() => void remove()}
            >
              Delete
            </button>
          )}
          <button className="text-button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
