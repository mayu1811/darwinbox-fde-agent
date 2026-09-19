import { useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  Ban,
  Check,
  CircleHelp,
  Copy,
  Loader2,
  PencilLine,
  ShieldAlert,
  Users,
} from 'lucide-react'
import type { Escalation } from '../types'
import { ConfidenceBar } from './primitives'

const TYPE_META: Record<
  string,
  { label: string; icon: typeof AlertTriangle; blurb: string }
> = {
  AMBIGUOUS_MAPPING: {
    label: 'Ambiguous field mapping',
    icon: CircleHelp,
    blurb: 'Two target fields are equally plausible for this source column.',
  },
  MISSING_MANDATORY_FIELD: {
    label: 'Missing mandatory field',
    icon: ShieldAlert,
    blurb: 'A field the target platform requires is not present in any source file.',
  },
  DUPLICATE_CONFLICT: {
    label: 'Duplicate records conflict',
    icon: Users,
    blurb: 'The same employee appears in both sources with different values.',
  },
  VALIDATION_FAILURE: {
    label: 'Validation failure',
    icon: AlertTriangle,
    blurb: 'The record still fails validation after the automatic repair attempts.',
  },
  UNSAFE_VALUE: {
    label: 'Value cannot be cleaned safely',
    icon: AlertTriangle,
    blurb: 'Normalising this value would require a guess.',
  },
  DESTRUCTIVE_ACTION: {
    label: 'Destructive action',
    icon: ShieldAlert,
    blurb: 'This action cannot be undone automatically.',
  },
}

const SEVERITY_STYLES: Record<string, string> = {
  HIGH: 'border-amber-800/60 bg-amber-950/25',
  MEDIUM: 'border-ink-700 bg-ink-900/60',
  LOW: 'border-ink-800 bg-ink-900/40',
}

interface Props {
  escalation: Escalation
  onResolve: (
    id: number,
    body: { decision: string; value?: string | null; note?: string | null },
  ) => Promise<void>
}

export function EscalationCard({ escalation, onResolve }: Props) {
  const [custom, setCustom] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState<string | null>(null)

  const meta = TYPE_META[escalation.type] ?? {
    label: escalation.type,
    icon: AlertTriangle,
    blurb: '',
  }
  const Icon = meta.icon
  const resolved = escalation.status !== 'OPEN'

  async function act(decision: string, value?: string | null) {
    setBusy(value ?? decision)
    try {
      await onResolve(escalation.id, { decision, value, note: note || null })
    } finally {
      setBusy(null)
    }
  }

  if (resolved) {
    return (
      <div className="panel panel-pad animate-fade-in border-emerald-900/40">
        <div className="flex items-start gap-3">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-ink-300">{escalation.title}</div>
            <div className="mt-2 space-y-1 text-xs text-ink-500">
              <div className="flex items-center gap-1.5 text-emerald-400">
                <Check className="h-3 w-3" /> Resolved by {escalation.resolved_by} (
                {escalation.status.toLowerCase()})
              </div>
              {escalation.resolution?.value && (
                <div className="flex items-center gap-1.5 text-emerald-400">
                  <Check className="h-3 w-3" /> Applied:{' '}
                  <span className="font-mono text-ink-300">{escalation.resolution.value}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5 text-emerald-400">
                <Check className="h-3 w-3" /> Agent resumed and re-validated the affected records
              </div>
              {escalation.resolution?.note && (
                <div className="pt-1 italic text-ink-500">“{escalation.resolution.note}”</div>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      className={`panel panel-pad animate-fade-in border ${
        SEVERITY_STYLES[escalation.severity] ?? SEVERITY_STYLES.MEDIUM
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 rounded-lg bg-amber-950/60 p-2">
            <Icon className="h-4 w-4 text-amber-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-400">
                Review required
              </span>
              <span className="chip bg-ink-800 text-ink-400">{escalation.severity}</span>
            </div>
            <h3 className="mt-1 text-base font-semibold text-white">{meta.label}</h3>
            <p className="text-xs text-ink-500">{meta.blurb}</p>
          </div>
        </div>
        <span className="font-mono text-[11px] text-ink-600">#{escalation.id}</span>
      </div>

      {/* context */}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {escalation.source_field && (
          <Field label={escalation.type === 'AMBIGUOUS_MAPPING' ? 'Source field' : 'Field'}>
            <code className="text-sm text-white">{escalation.source_field}</code>
            {escalation.source_file && (
              <div className="text-[11px] text-ink-600">in {escalation.source_file}</div>
            )}
          </Field>
        )}
        {escalation.record_id && (
          <Field label="Record">
            <code className="text-sm text-white">{escalation.record_id}</code>
          </Field>
        )}
      </div>

      {escalation.sample_values.length > 0 && (
        <div className="mt-3">
          <div className="label mb-1.5">Sample values</div>
          <div className="flex flex-wrap gap-1.5">
            {escalation.sample_values.map((value, i) => (
              <code
                key={i}
                className="rounded bg-ink-850 px-2 py-1 font-mono text-[11px] text-ink-300"
              >
                {value}
              </code>
            ))}
          </div>
        </div>
      )}

      {/* agent reasoning */}
      <div className="mt-4 rounded-lg border border-ink-800 bg-ink-950/60 p-3">
        <div className="label mb-1.5">Why the agent stopped</div>
        <p className="text-sm leading-relaxed text-ink-300">{escalation.reason}</p>
        {escalation.agent_recommendation && (
          <p className="mt-2 text-xs leading-relaxed text-ink-500">
            {escalation.agent_recommendation}
          </p>
        )}
      </div>

      {/* decision */}
      <div className="mt-4">
        <div className="label mb-2">Decision</div>
        <div className="space-y-2">
          {escalation.candidate_values.map((candidate) => (
            <button
              key={candidate.value}
              disabled={busy !== null}
              onClick={() => act('CORRECTED', candidate.value)}
              className="group flex w-full items-start gap-3 rounded-lg border border-ink-700 bg-ink-850/60 p-3 text-left transition-colors hover:border-accent hover:bg-accent-soft disabled:opacity-50"
            >
              <div className="mt-0.5">
                {busy === candidate.value ? (
                  <Loader2 className="h-4 w-4 animate-spin text-accent" />
                ) : (
                  <ArrowRight className="h-4 w-4 text-ink-600 group-hover:text-accent" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <code className="text-sm font-medium text-white">{candidate.label}</code>
                  {candidate.confidence > 0 && (
                    <ConfidenceBar value={candidate.confidence} />
                  )}
                </div>
                {candidate.reason && (
                  <div className="mt-1 text-xs leading-relaxed text-ink-500">
                    {candidate.reason}
                  </div>
                )}
              </div>
            </button>
          ))}

          {showCustom ? (
            <div className="rounded-lg border border-ink-700 bg-ink-850/60 p-3">
              <label className="label">Enter the correct value</label>
              <div className="mt-2 flex gap-2">
                <input
                  autoFocus
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  placeholder={
                    escalation.type === 'AMBIGUOUS_MAPPING'
                      ? 'target field name, e.g. work_phone'
                      : 'corrected value'
                  }
                  className="flex-1 rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-sm text-white outline-none focus:border-accent"
                />
                <button
                  disabled={!custom.trim() || busy !== null}
                  onClick={() => act('CORRECTED', custom.trim())}
                  className="btn-primary"
                >
                  {busy === custom.trim() ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  Apply
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setShowCustom(true)}
              className="flex w-full items-center gap-2 rounded-lg border border-dashed border-ink-700 p-3 text-sm text-ink-400 transition-colors hover:border-ink-600 hover:text-ink-200"
            >
              <PencilLine className="h-4 w-4" />
              Enter a custom value
            </button>
          )}
        </div>

        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note for the audit trail (why you decided this)"
            className="flex-1 rounded-md border border-ink-800 bg-ink-950 px-3 py-2 text-xs text-ink-200 outline-none focus:border-ink-600"
          />
          <button
            disabled={busy !== null}
            onClick={() => act('REJECTED')}
            className="btn-danger shrink-0"
          >
            {busy === 'REJECTED' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Ban className="h-4 w-4" />
            )}
            Reject
          </button>
        </div>
        <p className="mt-2 flex items-start gap-1.5 text-[11px] text-ink-600">
          <Copy className="mt-0.5 h-3 w-3 shrink-0" />
          Rejecting excludes the affected {escalation.type === 'AMBIGUOUS_MAPPING'
            ? 'column'
            : 'record'}{' '}
          from this migration. Everything else continues automatically.
        </p>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-950/50 p-3">
      <div className="label mb-1">{label}</div>
      {children}
    </div>
  )
}
