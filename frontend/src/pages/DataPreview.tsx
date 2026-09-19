import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, ChevronDown, ChevronRight, User } from 'lucide-react'
import { api } from '../services/api'
import type { EmployeeRecord } from '../types'
import { EmptyState, RecordBadge, Spinner } from '../components/primitives'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'cleaned', label: 'Cleaned' },
  { key: 'duplicates', label: 'Duplicates' },
  { key: 'escalated', label: 'Escalated' },
  { key: 'invalid', label: 'Invalid' },
  { key: 'ready', label: 'Ready' },
  { key: 'pushed', label: 'Pushed' },
  { key: 'failed', label: 'Failed' },
] as const

export function DataPreview({ migrationId }: { migrationId: string }) {
  const [filter, setFilter] = useState<string>('all')
  const [rows, setRows] = useState<EmployeeRecord[] | null>(null)
  const [open, setOpen] = useState<number | null>(null)

  useEffect(() => {
    let active = true
    setRows(null)
    const load = () =>
      api.records(migrationId, filter).then((r) => {
        if (active) setRows(r)
      })
    void load()
    const t = window.setInterval(load, 4000)
    return () => {
      active = false
      window.clearInterval(t)
    }
  }, [migrationId, filter])

  const counts = useMemo(() => {
    if (!rows) return null
    return rows.length
  }, [rows])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              filter === f.key
                ? 'bg-accent text-white'
                : 'border border-ink-800 text-ink-400 hover:bg-ink-850 hover:text-ink-200'
            }`}
          >
            {f.label}
          </button>
        ))}
        {counts !== null && (
          <span className="ml-auto font-mono text-xs text-ink-500">{counts} records</span>
        )}
      </div>

      {!rows ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <EmptyState title="Nothing in this view" hint="Try a different filter." />
      ) : (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[1000px]">
            <thead>
              <tr>
                <th className="th w-8" />
                <th className="th">Source</th>
                <th className="th">Employee ID</th>
                <th className="th">Full name</th>
                <th className="th">Email</th>
                <th className="th">DOB</th>
                <th className="th">Joined</th>
                <th className="th">Department</th>
                <th className="th">Status</th>
                <th className="th">Record</th>
                <th className="th">Changes</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-850">
              {rows.map((r) => {
                const t = r.transformed
                const isOpen = open === r.id
                return (
                  <>
                    <tr
                      key={r.id}
                      onClick={() => setOpen(isOpen ? null : r.id)}
                      className={`cursor-pointer hover:bg-ink-850/50 ${
                        r.status === 'MERGED' ? 'opacity-55' : ''
                      }`}
                    >
                      <td className="cell text-ink-600">
                        {isOpen ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </td>
                      <td className="cell whitespace-nowrap text-[11px] text-ink-500">
                        {r.source_file_name.replace('employees_', '').replace(/\.\w+$/, '')}
                        <span className="text-ink-700"> :{r.source_row_number}</span>
                      </td>
                      <td className="cell font-mono text-ink-200">{t.employee_id ?? '—'}</td>
                      <td className="cell text-ink-200">{t.full_name ?? '—'}</td>
                      <td className="cell text-ink-300">{t.email ?? <Missing />}</td>
                      <td className="cell font-mono text-xs text-ink-400">
                        {t.date_of_birth ?? <Missing />}
                      </td>
                      <td className="cell font-mono text-xs text-ink-400">
                        {t.joining_date ?? '—'}
                      </td>
                      <td className="cell text-ink-300">{t.department ?? '—'}</td>
                      <td className="cell">
                        {t.status ? (
                          <span
                            className={`chip ${
                              t.status === 'active'
                                ? 'bg-emerald-950 text-emerald-300'
                                : 'bg-ink-800 text-ink-400'
                            }`}
                          >
                            {t.status}
                          </span>
                        ) : (
                          <Missing />
                        )}
                      </td>
                      <td className="cell">
                        <RecordBadge status={r.status} />
                      </td>
                      <td className="cell">
                        {r.changes.length > 0 ? (
                          <span className="chip bg-cyan-950 text-cyan-300">
                            {r.changes.length}
                          </span>
                        ) : (
                          <span className="text-xs text-ink-700">—</span>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr key={`${r.id}-d`} className="bg-ink-950/70">
                        <td colSpan={11} className="px-5 py-4">
                          <div className="grid gap-5 lg:grid-cols-2">
                            <div>
                              <div className="label mb-2">
                                Transformations ({r.changes.length})
                              </div>
                              {r.changes.length === 0 && (
                                <p className="text-xs text-ink-600">
                                  Nothing needed changing on this row.
                                </p>
                              )}
                              <div className="space-y-1.5">
                                {r.changes.map((c, i) => (
                                  <div
                                    key={i}
                                    className="flex flex-wrap items-center gap-2 text-xs"
                                  >
                                    <code className="w-28 shrink-0 text-ink-400">{c.field}</code>
                                    <code className="rounded bg-rose-950/40 px-1.5 py-0.5 text-rose-300">
                                      {c.before === null || c.before === '' ? '∅' : c.before}
                                    </code>
                                    <ArrowRight className="h-3 w-3 text-ink-600" />
                                    <code className="rounded bg-emerald-950/40 px-1.5 py-0.5 text-emerald-300">
                                      {c.after === null || c.after === '' ? '∅' : c.after}
                                    </code>
                                    <span
                                      className={`chip ${
                                        c.actor === 'human'
                                          ? 'bg-amber-950 text-amber-300'
                                          : 'bg-ink-850 text-ink-500'
                                      }`}
                                    >
                                      {c.actor === 'human' && <User className="h-3 w-3" />}
                                      {c.rule}
                                    </span>
                                  </div>
                                ))}
                              </div>

                              {r.dedupe_notes.length > 0 && (
                                <>
                                  <div className="label mb-1.5 mt-4">Deduplication</div>
                                  <ul className="space-y-1 text-xs text-ink-400">
                                    {r.dedupe_notes.map((n, i) => (
                                      <li key={i}>· {n}</li>
                                    ))}
                                  </ul>
                                </>
                              )}

                              {r.validation_errors.length > 0 && (
                                <>
                                  <div className="label mb-1.5 mt-4">Validation errors</div>
                                  <ul className="space-y-1 text-xs text-rose-300">
                                    {r.validation_errors.map((e, i) => (
                                      <li key={i}>· {e.message}</li>
                                    ))}
                                  </ul>
                                </>
                              )}

                              {r.push_error && (
                                <>
                                  <div className="label mb-1.5 mt-4">
                                    Target response ({r.push_attempt_count} attempt
                                    {r.push_attempt_count === 1 ? '' : 's'})
                                  </div>
                                  <p className="text-xs text-rose-300">
                                    [{r.push_failure_kind}] {r.push_error}
                                  </p>
                                </>
                              )}
                            </div>

                            <div>
                              <div className="label mb-2">Source row (verbatim)</div>
                              <div className="max-h-64 overflow-y-auto rounded-lg border border-ink-800 bg-ink-950 p-3">
                                <table className="w-full text-xs">
                                  <tbody className="divide-y divide-ink-850">
                                    {Object.entries(r.raw).map(([k, v]) => (
                                      <tr key={k}>
                                        <td className="py-1 pr-3 text-ink-500">{k}</td>
                                        <td className="py-1 font-mono text-ink-300">
                                          {v === '' ? (
                                            <span className="text-ink-700">∅ empty</span>
                                          ) : (
                                            `"${v}"`
                                          )}
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Missing() {
  return <span className="text-xs italic text-rose-400/80">missing</span>
}
