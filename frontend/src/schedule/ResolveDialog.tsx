/** The choice presented when new work will not fit the settled schedule.
 *
 * Nothing has been written at this point. Each button below is a different
 * answer sent back to the same endpoint, and every one of them commits. */

import { useState } from 'react'

import type { GenerateRequest, NeedsDecision } from './generate'
import { toInstant } from './generate'

type Props = {
  result: NeedsDecision
  /** Titles for the events named in `unmet`, which carries only ids. */
  titleOf: (eventId: number) => string
  onResolve: (request: GenerateRequest) => void
  onCancel: () => void
  busy: boolean
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

export function ResolveDialog({
  result,
  titleOf,
  onResolve,
  onCancel,
  busy,
}: Props) {
  const [extending, setExtending] = useState(false)
  const [date, setDate] = useState(today)
  const [from, setFrom] = useState('18:00')
  const [to, setTo] = useState('21:00')

  const { rebuild } = result.options
  const invalidWindow = to <= from

  return (
    <div className="modal-scrim" role="presentation" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="resolve-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="resolve-title">This won't fit</h2>

        <p className="field-hint">
          Your schedule is settled for the next few days, and there isn't enough
          free time left for:
        </p>

        <ul className="unmet-list">
          {result.unmet.map((item) => {
            const short = item.periods_needed - item.periods_allocated
            return (
              <li key={item.event_id}>
                <strong>{titleOf(item.event_id)}</strong>
                <span>
                  {item.reason === 'overdue'
                    ? 'already past its due date'
                    : `${short} more ${short === 1 ? 'period' : 'periods'} needed`}
                </span>
              </li>
            )
          })}
        </ul>

        {!extending ? (
          <div className="modal-actions">
            <button
              className="button"
              disabled={busy}
              onClick={() => setExtending(true)}
            >
              Work outside my usual hours
            </button>

            <button
              className="button"
              disabled={busy || !rebuild.resolves}
              title={
                rebuild.resolves
                  ? undefined
                  : 'Rebuilding would not free up enough time either'
              }
              onClick={() => onResolve({ strategy: 'rebuild' })}
            >
              Rebuild my whole schedule
            </button>

            <button
              className="button quiet"
              disabled={busy}
              onClick={() => onResolve({ accept_unmet: true })}
            >
              Leave it unscheduled
            </button>

            <button className="text-button" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
          </div>
        ) : (
          <>
            <p className="field-hint">
              When are you willing to work? This is used once, and does not
              change your usual hours.
            </p>

            <div className="window-picker">
              <label>
                Date
                <input
                  type="date"
                  value={date}
                  onChange={(e) => setDate(e.target.value)}
                />
              </label>
              <label>
                From
                <input
                  type="time"
                  value={from}
                  onChange={(e) => setFrom(e.target.value)}
                />
              </label>
              <label>
                To
                <input
                  type="time"
                  value={to}
                  onChange={(e) => setTo(e.target.value)}
                />
              </label>
            </div>

            {invalidWindow && (
              <p className="field-warning" role="alert">
                The end time needs to be after the start time.
              </p>
            )}

            <div className="modal-actions">
              <button
                className="button"
                disabled={busy || invalidWindow}
                onClick={() =>
                  onResolve({
                    extra_windows: [
                      {
                        starts_at: toInstant(date, from),
                        ends_at: toInstant(date, to),
                      },
                    ],
                  })
                }
              >
                Use this time
              </button>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => setExtending(false)}
              >
                Back
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
