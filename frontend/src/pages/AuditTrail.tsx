import { useEffect, useState } from 'react'
import { ArrowRight, Search } from 'lucide-react'
import { api } from '../services/api'
import type { AuditEvent } from '../types'
import { ActorTag, EmptyState, Spinner } from '../components/primitives'

const ACTORS = [
  { key: '', label: 'Everyone' },
  { key: 'agent', label: 'Agent' },
  { key: 'human', label: 'Human' },
  { key: 'target_api', label: 'Target API' },
]

const CATEGORIES = [
  { key: '', label: 'All events' },
  { key: 'mappings', label: 'Mappings' },
  { key: 'transformations', label: 'Transformations' },
  { key: 'escalations', label: 'Escalations' },
  { key: 'errors', label: 'Errors' },
  { key: 'api', label: 'API' },
  { key: 'rollback', label: 'Rollback' },
]

export function AuditTrail({ migrationId }: { migrationId: string }) {
  const [actor, setActor] = useState('')
  const [category, setCategory] = useState('')
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<AuditEvent[] | null>(null)

  useEffect(() => {
    let active = true
    const handle = window.setTimeout(() => {
      api.audit(migrationId, { actor, category, q }).then((r) => {
        if (active) setRows(r)
      })
    }, 200)
    return () => {
      active = false
      window.clearTimeout(handle)
    }
  }, [migrationId, actor, category, q])

  return (
    <div className="space-y-4">
      <div className="panel panel-pad">
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[220px]">
            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-600" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search summaries and reasons…"
              className="w-full rounded-lg border border-ink-800 bg-ink-950 py-2 pl-9 pr-3 text-sm text-ink-200 outline-none focus:border-accent"
            />
          </div>
          <Select value={actor} onChange={setActor} options={ACTORS} />
          <Select value={category} onChange={setCategory} options={CATEGORIES} />
          {rows && <span className="font-mono text-xs text-ink-500">{rows.length} events</span>}
        </div>
      </div>

      {!rows ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <EmptyState title="No matching audit events" />
      ) : (
        <div className="panel divide-y divide-ink-850">
          {rows.map((e) => (
            <div key={e.id} className="flex gap-4 px-5 py-3 hover:bg-ink-850/30">
              <div className="w-20 shrink-0 pt-0.5 font-mono text-[11px] text-ink-600">
                {new Date(e.created_at).toLocaleTimeString()}
              </div>
              <div className="w-24 shrink-0 pt-0.5">
                <ActorTag actor={e.actor} aiAssisted={e.ai_assisted} />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[10px] uppercase tracking-wider text-ink-600">
                    {e.event}
                  </span>
                  {e.record_ref && (
                    <code className="text-[10px] text-ink-500">{e.record_ref}</code>
                  )}
                  {e.confidence !== null && (
                    <span className="font-mono text-[10px] text-ink-500">
                      conf {Math.round(e.confidence * 100)}%
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-sm text-ink-200">{e.summary}</div>
                {e.reason && (
                  <div className="mt-0.5 text-xs leading-relaxed text-ink-500">{e.reason}</div>
                )}
                {(e.before || e.after) && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                    <code className="rounded bg-rose-950/40 px-1.5 py-0.5 text-rose-300">
                      {fmt(e.before)}
                    </code>
                    <ArrowRight className="h-3 w-3 text-ink-600" />
                    <code className="rounded bg-emerald-950/40 px-1.5 py-0.5 text-emerald-300">
                      {fmt(e.after)}
                    </code>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function fmt(value: Record<string, unknown> | null) {
  if (value === null || value === undefined) return '∅'
  return Object.entries(value)
    .map(([k, v]) => `${k}=${v === null || v === '' ? '∅' : JSON.stringify(v)}`)
    .join(' ')
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: { key: string; label: string }[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-ink-800 bg-ink-950 px-3 py-2 text-sm text-ink-300 outline-none focus:border-accent"
    >
      {options.map((o) => (
        <option key={o.key} value={o.key}>
          {o.label}
        </option>
      ))}
    </select>
  )
}
