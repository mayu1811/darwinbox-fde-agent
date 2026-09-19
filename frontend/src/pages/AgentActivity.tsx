import { Radio, WifiOff } from 'lucide-react'
import type { ActivityEvent, Migration } from '../types'
import { ActorTag, EmptyState, ProgressBar, StateBadge } from '../components/primitives'

const PIPELINE = [
  { state: 'DISCOVERING', label: 'Ingest', detail: 'read CSV / XLSX verbatim' },
  { state: 'PROFILING', label: 'Profile', detail: 'infer column types and statistics' },
  { state: 'MAPPING', label: 'Map', detail: 'score source columns against the target schema' },
  { state: 'CLEANING', label: 'Clean', detail: 'deterministic, reversible normalisation' },
  { state: 'DEDUPLICATING', label: 'Deduplicate', detail: 'match, merge, reconcile' },
  { state: 'VALIDATING', label: 'Validate', detail: 'schema checks + bounded auto-repair' },
  { state: 'WAITING_FOR_HUMAN', label: 'Escalate', detail: 'only genuine ambiguity' },
  { state: 'READY_TO_PUSH', label: 'Ready', detail: 'validated payloads' },
  { state: 'PUSHING', label: 'Push', detail: 'target API with retry' },
  { state: 'COMPLETED', label: 'Complete', detail: 'audit trail written' },
]

const ORDER = PIPELINE.map((p) => p.state)

export function AgentActivity({
  migration,
  activity,
  connected,
}: {
  migration: Migration
  activity: ActivityEvent[]
  connected: boolean
}) {
  const currentIndex = ORDER.indexOf(migration.state)
  const feed = [...activity].reverse()

  return (
    <div className="grid gap-6 lg:grid-cols-5">
      <div className="panel panel-pad lg:col-span-2">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-white">Pipeline</h2>
          <StateBadge state={migration.state} />
        </div>
        <ol className="relative space-y-1">
          {PIPELINE.map((step, i) => {
            const active = migration.state === step.state
            const done = currentIndex > i && currentIndex !== -1
            return (
              <li
                key={step.state}
                className={`flex gap-3 rounded-lg px-2.5 py-2 ${
                  active ? 'bg-accent-soft' : ''
                }`}
              >
                <div className="flex flex-col items-center">
                  <span
                    className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${
                      active
                        ? 'bg-accent animate-pulse-ring'
                        : done
                          ? 'bg-emerald-500'
                          : 'bg-ink-700'
                    }`}
                  />
                  {i < PIPELINE.length - 1 && (
                    <span
                      className={`mt-1 w-px flex-1 ${done ? 'bg-emerald-900' : 'bg-ink-800'}`}
                    />
                  )}
                </div>
                <div className="pb-1">
                  <div
                    className={`text-sm ${
                      active ? 'font-medium text-white' : done ? 'text-ink-300' : 'text-ink-600'
                    }`}
                  >
                    {step.label}
                  </div>
                  <div className="text-[11px] text-ink-600">{step.detail}</div>
                </div>
              </li>
            )
          })}
        </ol>
        <div className="mt-4 border-t border-ink-800 pt-4">
          <div className="label mb-2">Current step</div>
          <p className="mb-3 text-xs text-ink-300">{migration.current_step}</p>
          <ProgressBar done={migration.progress_done} total={migration.progress_total} />
        </div>
      </div>

      <div className="panel lg:col-span-3">
        <div className="flex items-center justify-between border-b border-ink-800 px-5 py-3">
          <h2 className="text-sm font-semibold text-white">Live agent log</h2>
          <span
            className={`chip ${
              connected ? 'bg-emerald-950 text-emerald-300' : 'bg-ink-800 text-ink-400'
            }`}
          >
            {connected ? <Radio className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
            {connected ? 'streaming' : 'reconnecting'}
          </span>
        </div>
        <div className="max-h-[70vh] overflow-y-auto">
          {feed.length === 0 ? (
            <EmptyState title="No activity yet" hint="Events appear here as the agent works." />
          ) : (
            <div className="divide-y divide-ink-850">
              {feed.map((event) => (
                <div key={event.seq} className="flex animate-fade-in gap-3 px-4 py-2.5 text-xs">
                  <span className="w-16 shrink-0 font-mono text-[10px] text-ink-600">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                  <span className="w-24 shrink-0">
                    <EventChip event={event} />
                  </span>
                  <span className="min-w-0 flex-1 leading-relaxed text-ink-300">
                    {describe(event)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EventChip({ event }: { event: ActivityEvent }) {
  if (event.type === 'audit') {
    return <ActorTag actor={event.payload.actor} aiAssisted={event.payload.ai_assisted} />
  }
  const styles: Record<string, string> = {
    state: 'bg-indigo-950 text-indigo-300',
    escalation: 'bg-amber-950 text-amber-300',
    push: 'bg-blue-950 text-blue-300',
    rollback: 'bg-orange-950 text-orange-300',
  }
  return <span className={`chip ${styles[event.type] ?? 'bg-ink-800'}`}>{event.type}</span>
}

function describe(event: ActivityEvent): string {
  const p = event.payload
  switch (event.type) {
    case 'state':
      return `${p.state} — ${p.current_step}`
    case 'escalation':
      return p.action === 'created'
        ? `Escalation raised: ${p.title}`
        : `Escalation #${p.escalation_id} ${p.decision}${p.value ? ` → ${p.value}` : ''}`
    case 'push':
      return `${p.employee_id} attempt ${p.attempt}: ${p.status}${p.error ? ` — ${p.error}` : ''}`
    case 'rollback':
      return `${p.employee_id} removed from the target (${p.status})`
    default:
      return p.summary ?? JSON.stringify(p)
  }
}
