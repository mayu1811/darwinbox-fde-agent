import { useEffect } from 'react'
import { AlertTriangle, Loader2, X } from 'lucide-react'

export interface ConfirmRequest {
  title: string
  body: string
  consequence?: string
  confirmLabel: string
  destructive?: boolean
  onConfirm: () => void | Promise<void>
}

/**
 * In-app confirmation for irreversible actions.
 *
 * Destructive operations are the one thing the agent will never do on its own,
 * so the UI makes the human say it out loud - and spells out exactly what is
 * about to happen before they do.
 */
export function ConfirmDialog({
  request,
  busy,
  onClose,
}: {
  request: ConfirmRequest | null
  busy: boolean
  onClose: () => void
}) {
  useEffect(() => {
    if (!request) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [request, busy, onClose])

  if (!request) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        className="panel w-full max-w-md animate-fade-in border-ink-700 p-6 shadow-2xl"
      >
        <div className="flex items-start gap-3">
          <div
            className={`rounded-lg p-2 ${
              request.destructive ? 'bg-rose-950/60' : 'bg-accent-soft'
            }`}
          >
            <AlertTriangle
              className={`h-4 w-4 ${request.destructive ? 'text-rose-400' : 'text-accent'}`}
            />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-white">{request.title}</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-ink-400">{request.body}</p>
            {request.consequence && (
              <p className="mt-3 rounded-lg border border-ink-800 bg-ink-950/60 p-3 text-xs leading-relaxed text-ink-400">
                {request.consequence}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            disabled={busy}
            className="text-ink-600 transition-colors hover:text-ink-300 disabled:opacity-40"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onClose} disabled={busy} className="btn-ghost">
            Cancel
          </button>
          <button
            onClick={() => void request.onConfirm()}
            disabled={busy}
            className={request.destructive ? 'btn-danger' : 'btn-primary'}
          >
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
            {request.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
