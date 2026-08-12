/** A yes/no question the user has to answer before something is removed.
 *
 * Used where the server has refused an action and explained why, so the message
 * shown here is the server's own wording rather than a second guess at it. */

type Props = {
  title: string
  message: string
  /** Wording for the destructive action, e.g. "Delete it anyway". */
  confirmLabel: string
  onConfirm: () => void
  onCancel: () => void
  busy: boolean
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
}: Props) {
  return (
    <div className="modal-scrim" role="presentation" onClick={onCancel}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="confirm-title">{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="Close"
            disabled={busy}
            onClick={onCancel}
          >
            ×
          </button>
        </div>

        <p className="field-hint">{message}</p>

        <div className="modal-actions">
          <button className="button danger" disabled={busy} onClick={onConfirm}>
            {busy ? 'Working…' : confirmLabel}
          </button>
          <button className="text-button" disabled={busy} onClick={onCancel}>
            Keep it
          </button>
        </div>
      </div>
    </div>
  )
}
