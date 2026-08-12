/** Tests for the event form.
 *
 * One form does two jobs — creating an event and correcting one the importer
 * guessed wrong — and the shape it submits has to match the event type, because
 * the database has a CHECK constraint tying the time columns to it. Sending a
 * deadline with a start time is rejected at the far end of the stack, so the
 * assertions here are mostly about the exact draft that leaves the form. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { EventEditor } from './EventEditor'
import * as api from './api'
import type { ScheduleEvent } from '../schedule/types'

// The pure date helpers stay real — they decide what the inputs display, so
// stubbing them would test nothing. Only the three calls that reach the network
// are replaced, which also lets each test read the draft that was submitted.
vi.mock('./api', async (importOriginal) => {
  const real = await importOriginal<typeof api>()
  return {
    ...real,
    createEvent: vi.fn(async () => ({}) as ScheduleEvent),
    updateEvent: vi.fn(async () => ({}) as ScheduleEvent),
    deleteEvent: vi.fn(async () => undefined),
  }
})

function existing(over: Partial<ScheduleEvent> = {}): ScheduleEvent {
  return {
    id: 42,
    title: 'Standup',
    description: 'Daily',
    event_type: 'one_time',
    source: 'manual',
    availability: 'busy',
    starts_at: '2026-08-10T09:00:00Z',
    ends_at: '2026-08-10T10:00:00Z',
    due_at: null,
    is_all_day: false,
    expected_prep_minutes: null,
    type_locked: true,
    ...over,
  }
}

function draw(event: ScheduleEvent | null = null) {
  const onClose = vi.fn()
  const onSaved = vi.fn()
  render(<EventEditor event={event} onClose={onClose} onSaved={onSaved} />)
  return { onClose, onSaved }
}

const created = () => vi.mocked(api.createEvent).mock.calls[0][0]
const updated = () => vi.mocked(api.updateEvent).mock.calls[0]

beforeEach(() => {
  vi.clearAllMocks()
})

// --- Which job it is doing ---------------------------------------------

describe('creating versus correcting', () => {
  it('is titled for adding when there is no event', () => {
    draw()

    expect(screen.getByRole('heading')).toHaveTextContent('Add an event')
  })

  it('is titled for editing when there is one', () => {
    draw(existing())

    expect(screen.getByRole('heading')).toHaveTextContent('Event details')
  })

  it('starts as a timed event, the common case', () => {
    draw()

    expect(screen.getByRole('button', { name: /^Event/ })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('pre-fills the fields of the event being corrected', () => {
    draw(existing())

    expect(screen.getByLabelText('Title')).toHaveValue('Standup')
    expect(screen.getByLabelText('Notes')).toHaveValue('Daily')
  })

  it('opens on the deadline shape for a deadline', () => {
    draw(existing({ event_type: 'deadline', starts_at: null, ends_at: null, due_at: '2026-08-14T17:00:00Z' }))

    expect(screen.getByLabelText('Due')).toBeInTheDocument()
    expect(screen.queryByLabelText('Starts')).toBeNull()
  })
})

// --- Switching type swaps the fields -----------------------------------

describe('choosing what kind of thing it is', () => {
  it('swaps the time fields for a due date and an estimate', async () => {
    draw()
    expect(screen.getByLabelText('Starts')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Deadline/ }))

    expect(screen.getByLabelText('Due')).toBeInTheDocument()
    expect(screen.getByLabelText(/How long will it take/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Starts')).toBeNull()
    expect(screen.queryByLabelText('Ends')).toBeNull()
  })

  it('offers the availability choices only for a timed event', async () => {
    draw()
    expect(screen.getByRole('button', { name: /Time to work/ })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^Deadline/ }))

    // A deadline is a moment, so "what should the schedule do" has no meaning.
    expect(screen.queryByRole('button', { name: /Time to work/ })).toBeNull()
  })

  it('can switch back', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: /^Deadline/ }))
    await userEvent.click(screen.getByRole('button', { name: /^Event/ }))

    expect(screen.getByLabelText('Starts')).toBeInTheDocument()
  })
})

// --- What gets submitted ------------------------------------------------

describe('saving a timed event', () => {
  it('sends a span and no due date', async () => {
    const { onSaved } = draw()

    await userEvent.type(screen.getByLabelText('Title'), 'Coffee with Sam')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const draft = created()
    expect(draft.title).toBe('Coffee with Sam')
    expect(draft.event_type).toBe('one_time')
    expect(draft.starts_at).toBeTruthy()
    expect(draft.ends_at).toBeTruthy()
    expect(draft.due_at).toBeNull()
    expect(onSaved).toHaveBeenCalledOnce()
  })

  it('includes the availability the user picked', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: /Time to work/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(created().availability).toBe('work_window')
  })

  it('can mark the event as the day\'s meal', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: /^Meal/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(created().availability).toBe('meal')
  })
})

describe('saving a deadline', () => {
  it('sends a due date and clears the span', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: /^Deadline/ }))
    await userEvent.type(screen.getByLabelText('Title'), 'Essay 2')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    const draft = created()
    expect(draft.event_type).toBe('deadline')
    expect(draft.due_at).toBeTruthy()
    // The CHECK constraint rejects a deadline that also has a span.
    expect(draft.starts_at).toBeNull()
    expect(draft.ends_at).toBeNull()
  })

  it('sends the prep estimate as a number', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: /^Deadline/ }))
    await userEvent.type(screen.getByLabelText(/How long will it take/), '120')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(created().expected_prep_minutes).toBe(120)
  })

  it('sends no estimate when the user is not sure', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: /^Deadline/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    // Null means "unknown", which the engine reads as one period, not zero.
    expect(created().expected_prep_minutes).toBeNull()
  })
})

describe('saving in general', () => {
  it('falls back to a placeholder rather than an empty title', async () => {
    draw()

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(created().title).toBe('Untitled')
  })

  it('trims whitespace, and treats a blank note as no note', async () => {
    draw()

    await userEvent.type(screen.getByLabelText('Title'), '  Spaced  ')
    await userEvent.type(screen.getByLabelText('Notes'), '   ')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(created().title).toBe('Spaced')
    expect(created().description).toBeNull()
  })

  it('updates rather than creates when correcting an event', async () => {
    draw(existing())

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(api.createEvent).not.toHaveBeenCalled()
    expect(updated()[0]).toBe(42)
  })

  it('shows the reason the server gave when a save fails', async () => {
    vi.mocked(api.createEvent).mockRejectedValueOnce(
      new Error('A deadline needs a due date'),
    )
    const { onSaved } = draw()

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A deadline needs a due date',
    )
    expect(onSaved).not.toHaveBeenCalled()
  })
})

// --- Deleting -----------------------------------------------------------

describe('deleting an event', () => {
  it('is offered for an event the user created', () => {
    draw(existing())

    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })

  it('is not offered while creating one', () => {
    draw()

    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
  })

  it('is not offered for an imported event, which would come back', () => {
    draw(existing({ source: 'imported' }))

    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
  })

  it('asks first, then deletes', async () => {
    const { onSaved } = draw(existing())

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(window.confirm).toHaveBeenCalled()
    expect(api.deleteEvent).toHaveBeenCalledWith(42)
    expect(onSaved).toHaveBeenCalledOnce()
  })

  it('does nothing when the question is declined', async () => {
    vi.mocked(window.confirm).mockReturnValueOnce(false)
    draw(existing())

    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    expect(api.deleteEvent).not.toHaveBeenCalled()
  })
})

// --- Handing an event back to inference ---------------------------------

describe('undoing a correction', () => {
  it('is offered on an imported event the user has customised', () => {
    draw(existing({ source: 'imported', type_locked: true }))

    expect(
      screen.getByRole('button', { name: 'Undo my changes' }),
    ).toBeInTheDocument()
  })

  it('is not offered on one the importer still owns', () => {
    draw(existing({ source: 'imported', type_locked: false }))

    expect(screen.queryByRole('button', { name: 'Undo my changes' })).toBeNull()
  })

  it('is not offered on a manual event, which was never inferred', () => {
    draw(existing({ source: 'manual', type_locked: true }))

    expect(screen.queryByRole('button', { name: 'Undo my changes' })).toBeNull()
  })

  it('unlocks the event so the next sync can reclassify it', async () => {
    draw(existing({ source: 'imported', type_locked: true }))

    await userEvent.click(screen.getByRole('button', { name: 'Undo my changes' }))

    expect(updated()).toEqual([42, { type_locked: false }])
  })
})

// --- Closing ------------------------------------------------------------

describe('closing', () => {
  it('closes on Cancel', async () => {
    const { onClose } = draw()

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes when the backdrop is clicked', async () => {
    const { onClose } = draw()

    await userEvent.click(screen.getByRole('presentation'))

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('stays open when the dialog itself is clicked', async () => {
    const { onClose } = draw()

    await userEvent.click(screen.getByRole('dialog'))

    expect(onClose).not.toHaveBeenCalled()
  })
})
