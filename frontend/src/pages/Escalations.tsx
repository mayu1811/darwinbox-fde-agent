import { CheckCircle2 } from 'lucide-react'
import { EscalationCard } from '../components/EscalationCard'
import { EmptyState, SectionTitle } from '../components/primitives'
import type { Escalation } from '../types'

export function Escalations({
  escalations,
  onResolve,
}: {
  escalations: Escalation[]
  onResolve: (
    id: number,
    body: { decision: string; value?: string | null; note?: string | null },
  ) => Promise<void>
}) {
  const open = escalations.filter((e) => e.status === 'OPEN')
  const resolved = escalations.filter((e) => e.status !== 'OPEN')

  return (
    <div className="space-y-6">
      <div className="panel panel-pad">
        <SectionTitle>Why these — and only these — reached you</SectionTitle>
        <div className="grid gap-4 text-xs leading-relaxed sm:grid-cols-2">
          <div>
            <div className="mb-1.5 font-medium text-emerald-400">Handled without you</div>
            <ul className="space-y-1 text-ink-400">
              <li>· whitespace, casing and email normalisation</li>
              <li>· date conversion to ISO-8601 (column profiled once, then deterministic)</li>
              <li>· exact-duplicate rows and non-conflicting merges</li>
              <li>· field mappings above the confidence and margin thresholds</li>
              <li>· transient target API failures (retried with backoff)</li>
            </ul>
          </div>
          <div>
            <div className="mb-1.5 font-medium text-amber-400">Brought to you</div>
            <ul className="space-y-1 text-ink-400">
              <li>· two target fields with near-identical mapping confidence</li>
              <li>· a mandatory field absent from every source</li>
              <li>· duplicates disagreeing on identity or employment status</li>
              <li>· records still invalid after two automatic repair attempts</li>
              <li>· anything destructive or irreversible</li>
            </ul>
          </div>
        </div>
      </div>

      {open.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="Nothing needs your attention"
            hint="The agent resolved everything within its autonomy boundary."
          />
        </div>
      ) : (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-white">
            Awaiting your decision ({open.length})
          </h2>
          {open.map((e) => (
            <EscalationCard key={e.id} escalation={e} onResolve={onResolve} />
          ))}
        </div>
      )}

      {resolved.length > 0 && (
        <div className="space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-ink-400">
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
            Resolved ({resolved.length})
          </h2>
          {resolved.map((e) => (
            <EscalationCard key={e.id} escalation={e} onResolve={onResolve} />
          ))}
        </div>
      )}
    </div>
  )
}
