import { useEffect, useState } from 'react'
import { CheckCircle2, Database, RefreshCw, XCircle } from 'lucide-react'
import { api } from '../services/api'
import type { PushAttempt, TargetEmployee } from '../types'
import { EmptyState, SectionTitle, Spinner, StatCard } from '../components/primitives'

export function TargetPush({ migrationId }: { migrationId: string }) {
  const [attempts, setAttempts] = useState<PushAttempt[] | null>(null)
  const [target, setTarget] = useState<TargetEmployee[] | null>(null)

  useEffect(() => {
    let active = true
    const load = () =>
      Promise.all([api.pushAttempts(migrationId), api.targetEmployees(migrationId)]).then(
        ([a, t]) => {
          if (active) {
            setAttempts(a)
            setTarget(t)
          }
        },
      )
    void load()
    const timer = window.setInterval(load, 2500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [migrationId])

  if (!attempts || !target) return <Spinner />

  const byEmployee = attempts.reduce<Record<string, PushAttempt[]>>((acc, a) => {
    ;(acc[a.employee_id] ??= []).push(a)
    return acc
  }, {})
  const entries = Object.entries(byEmployee).sort(([a], [b]) => a.localeCompare(b))

  const succeeded = entries.filter(([, list]) =>
    list.some((a) => a.status === 'success'),
  ).length
  const failed = entries.length - succeeded
  const retried = entries.filter(([, list]) => list.length > 1).length

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard label="In target platform" value={target.length} tone="good" icon={Database} />
        <StatCard label="Succeeded" value={succeeded} tone="good" icon={CheckCircle2} />
        <StatCard label="Failed" value={failed} tone={failed ? 'bad' : 'default'} icon={XCircle} />
        <StatCard
          label="Needed a retry"
          value={retried}
          hint="transient target errors"
          icon={RefreshCw}
        />
      </div>

      <div className="panel panel-pad">
        <SectionTitle>Push attempts per record</SectionTitle>
        {entries.length === 0 ? (
          <EmptyState
            title="Nothing pushed yet"
            hint="The agent pushes once every blocking escalation is resolved."
          />
        ) : (
          <div className="space-y-1.5">
            {entries.map(([employeeId, list]) => {
              const last = list[list.length - 1]
              const ok = last.status === 'success'
              return (
                <div
                  key={employeeId}
                  className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-800 bg-ink-950/50 px-3 py-2.5"
                >
                  <code className="w-24 shrink-0 text-sm text-ink-200">{employeeId}</code>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {list.map((a) => (
                      <span
                        key={a.id}
                        title={a.error ?? 'accepted'}
                        className={`chip ${
                          a.status === 'success'
                            ? 'bg-emerald-950 text-emerald-300'
                            : a.failure_kind === 'transient'
                              ? 'bg-amber-950 text-amber-300'
                              : 'bg-rose-950 text-rose-300'
                        }`}
                      >
                        #{a.attempt} {a.status === 'success' ? '✓' : '✕'}
                      </span>
                    ))}
                  </div>
                  <div className="min-w-0 flex-1 truncate text-xs text-ink-500">
                    {ok
                      ? list.length > 1
                        ? `Recovered automatically after ${list.length - 1} transient failure(s)`
                        : 'Accepted on the first attempt'
                      : last.error}
                  </div>
                  {!ok && (
                    <span
                      className={`chip shrink-0 ${
                        last.failure_kind === 'permanent'
                          ? 'bg-rose-950 text-rose-300'
                          : 'bg-amber-950 text-amber-300'
                      }`}
                    >
                      {last.failure_kind === 'permanent' ? 'not retryable' : 'retryable'}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      <div className="panel overflow-hidden">
        <div className="border-b border-ink-800 px-5 py-3">
          <h3 className="text-sm font-semibold text-white">
            Mock target platform — current contents
          </h3>
          <p className="mt-0.5 text-xs text-ink-500">
            Tagged with <code>{migrationId}</code>, which is what makes rollback exact.
          </p>
        </div>
        {target.length === 0 ? (
          <EmptyState title="Target platform is empty" />
        ) : (
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">Employee ID</th>
                  <th className="th">Name</th>
                  <th className="th">Email</th>
                  <th className="th">Mobile</th>
                  <th className="th">Department</th>
                  <th className="th">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-850">
                {target.map((row) => (
                  <tr key={row.employee_id} className="hover:bg-ink-850/40">
                    <td className="cell font-mono text-ink-200">{row.employee_id}</td>
                    <td className="cell text-ink-300">{row.payload.full_name}</td>
                    <td className="cell text-ink-400">{row.payload.email}</td>
                    <td className="cell font-mono text-xs text-ink-400">
                      {row.payload.mobile_phone ?? '—'}
                    </td>
                    <td className="cell text-ink-400">{row.payload.department ?? '—'}</td>
                    <td className="cell">
                      <span
                        className={`chip ${
                          row.payload.status === 'active'
                            ? 'bg-emerald-950 text-emerald-300'
                            : 'bg-ink-800 text-ink-400'
                        }`}
                      >
                        {row.payload.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
