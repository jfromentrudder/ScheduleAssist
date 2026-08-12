/** The choice offered when the user asks for a schedule.
 *
 * Generating is not destructive by default — settled periods are kept — but
 * "regenerate everything" is, so the two are separate buttons rather than a
 * checkbox someone can leave ticked by accident. Nothing has been written when
 * this opens, which is what makes closing it a real escape from a misclick. */

import type { GenerateRequest } from './generate'

type Props = {
  horizonDays: number
  onGenerate: (request: GenerateRequest) => void
  onClose: () => void
  busy: boolean
}

export function GenerateDialog({
  horizonDays,
  onGenerate,
  onClose,
  busy,
}: Props) {
  const days = `${horizonDays} ${horizonDays === 1 ? 'day' : 'days'}`

  return (
    <div className="modal-scrim" role="presentation" onClick={onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="generate-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="generate-title">Generate schedule</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="Close"
            disabled={busy}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <p className="field-hint">
          The next {days} of your schedule are settled. New work normally goes
          into the time that is still free, leaving those periods where they
          are.
        </p>

        <div className="modal-actions">
          <button
            className="button"
            disabled={busy}
            onClick={() => onGenerate({ strategy: 'additive' })}
          >
            {busy ? 'Generating…' : 'Keep settled periods'}
          </button>

          <button
            className="button quiet"
            disabled={busy}
            onClick={() => onGenerate({ strategy: 'rebuild' })}
          >
            Regenerate settled periods too
          </button>

          <p className="field-hint">
            Regenerating moves work you may already have planned around, so it
            is worth doing only when your settled days look wrong.
          </p>

          <button className="text-button" disabled={busy} onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
