import { useEffect, useState } from 'react'
import { ArrowRight, Bot, Sparkles, User } from 'lucide-react'
import { api } from '../services/api'
import type { FieldMapping } from '../types'
import { ConfidenceBar, EmptyState, SectionTitle, Spinner } from '../components/primitives'

const DECISION_STYLES: Record<string, string> = {
  AUTO_APPLIED: 'bg-emerald-950 text-emerald-300',
  HUMAN_RESOLVED: 'bg-amber-950 text-amber-300',
  ESCALATED: 'bg-amber-950 text-amber-300',
  IGNORED: 'bg-ink-800 text-ink-400',
}

export function Mappings({ migrationId }: { migrationId: string }) {
  const [rows, setRows] = useState<FieldMapping[] | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    let active = true
    const load = () =>
      api.mappings(migrationId).then((r) => {
        if (active) setRows(r)
      })
    void load()
    const t = window.setInterval(load, 3000)
    return () => {
      active = false
      window.clearInterval(t)
    }
  }, [migrationId])

  if (!rows) return <Spinner />
  if (rows.length === 0)
    return <EmptyState title="No mappings yet" hint="The agent has not reached the MAPPING step." />

  const byFile = rows.reduce<Record<string, FieldMapping[]>>((acc, row) => {
    ;(acc[row.source_file_name] ??= []).push(row)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      <div className="panel panel-pad">
        <SectionTitle>How mappings are decided</SectionTitle>
        <div className="grid gap-3 text-xs sm:grid-cols-3">
          <Rule tone="emerald" title="≥ 90% confidence">
            Applied automatically, provided no runner-up is within 10 points.
          </Rule>
          <Rule tone="amber" title="70 – 89% confidence">
            Applied only if the margin over the runner-up is ≥ 15 points, the field is not
            mandatory, and the inferred type fits. Otherwise escalated.
          </Rule>
          <Rule tone="rose" title="&lt; 70% confidence">
            Always escalated. Below 72% name similarity the column is left unmapped rather than
            forced into the closest field.
          </Rule>
        </div>
      </div>

      {Object.entries(byFile).map(([file, mappings]) => (
        <div key={file} className="panel overflow-hidden">
          <div className="border-b border-ink-800 px-5 py-3">
            <h3 className="font-mono text-sm text-white">{file}</h3>
          </div>
          {/* horizontal scroll keeps the decision column reachable on narrow screens */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px]">
            <thead>
              <tr>
                <th className="th">Source field</th>
                <th className="th">Target field</th>
                <th className="th">Confidence</th>
                <th className="th">Margin</th>
                <th className="th">Decision</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-850">
              {mappings.map((m) => (
                <>
                  <tr
                    key={m.id}
                    onClick={() => setExpanded(expanded === m.id ? null : m.id)}
                    className="cursor-pointer hover:bg-ink-850/50"
                  >
                    <td className="cell">
                      <code className="text-ink-200">{m.source_field}</code>
                      {m.sample_values.length > 0 && (
                        <div className="mt-0.5 truncate font-mono text-[10px] text-ink-600">
                          {m.sample_values.slice(0, 2).join(' · ')}
                        </div>
                      )}
                    </td>
                    <td className="cell">
                      <div className="flex items-center gap-2">
                        <ArrowRight className="h-3 w-3 text-ink-600" />
                        {m.target_field ? (
                          <code className="text-white">{m.target_field}</code>
                        ) : (
                          <span className="text-xs italic text-ink-600">not migrated</span>
                        )}
                      </div>
                    </td>
                    <td className="cell">
                      {m.target_field ? <ConfidenceBar value={m.confidence} /> : '—'}
                    </td>
                    <td className="cell font-mono text-xs text-ink-400">
                      {m.target_field ? `${Math.round(m.margin * 100)}%` : '—'}
                    </td>
                    <td className="cell">
                      <span className={`chip ${DECISION_STYLES[m.decision]}`}>
                        {m.decision === 'HUMAN_RESOLVED' ? (
                          <User className="h-3 w-3" />
                        ) : m.ai_assisted ? (
                          <Sparkles className="h-3 w-3" />
                        ) : (
                          <Bot className="h-3 w-3" />
                        )}
                        {m.decision.replace(/_/g, ' ').toLowerCase()}
                      </span>
                    </td>
                  </tr>
                  {expanded === m.id && (
                    <tr key={`${m.id}-detail`} className="bg-ink-950/60">
                      <td colSpan={5} className="px-5 py-4">
                        <div className="label mb-1">Agent reasoning</div>
                        <p className="mb-3 text-xs leading-relaxed text-ink-300">{m.reason}</p>
                        {m.resolved_by && (
                          <p className="mb-3 text-xs text-amber-400">
                            Decided by {m.resolved_by}
                          </p>
                        )}
                        {m.candidates.length > 0 && (
                          <>
                            <div className="label mb-1.5">All candidates considered</div>
                            <div className="space-y-1.5">
                              {m.candidates.map((c) => (
                                <div
                                  key={c.target_field}
                                  className="flex items-center gap-3 text-xs"
                                >
                                  <code className="w-36 shrink-0 text-ink-300">
                                    {c.target_field}
                                  </code>
                                  <ConfidenceBar value={c.confidence} />
                                  <span className="flex-1 text-ink-600">{c.reason}</span>
                                </div>
                              ))}
                            </div>
                          </>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      ))}
    </div>
  )
}

function Rule({
  tone,
  title,
  children,
}: {
  tone: 'emerald' | 'amber' | 'rose'
  title: string
  children: React.ReactNode
}) {
  const border = {
    emerald: 'border-emerald-900/50',
    amber: 'border-amber-900/50',
    rose: 'border-rose-900/50',
  }[tone]
  const text = {
    emerald: 'text-emerald-400',
    amber: 'text-amber-400',
    rose: 'text-rose-400',
  }[tone]
  return (
    <div className={`rounded-lg border ${border} bg-ink-950/50 p-3`}>
      <div className={`mb-1 font-mono text-xs font-semibold ${text}`}>{title}</div>
      <p className="leading-relaxed text-ink-400">{children}</p>
    </div>
  )
}
