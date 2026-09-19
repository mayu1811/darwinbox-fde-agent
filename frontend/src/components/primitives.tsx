import type { ReactNode } from 'react'
import { Bot, Loader2, Sparkles, User } from 'lucide-react'
import type { MigrationState, RecordStatus } from '../types'

/* ------------------------------------------------------------------ state */

const STATE_STYLES: Record<string, string> = {
  CREATED: 'bg-ink-800 text-ink-300',
  DISCOVERING: 'bg-sky-950 text-sky-300',
  PROFILING: 'bg-sky-950 text-sky-300',
  MAPPING: 'bg-indigo-950 text-indigo-300',
  CLEANING: 'bg-cyan-950 text-cyan-300',
  DEDUPLICATING: 'bg-violet-950 text-violet-300',
  VALIDATING: 'bg-teal-950 text-teal-300',
  WAITING_FOR_HUMAN: 'bg-amber-950 text-amber-300',
  READY_TO_PUSH: 'bg-blue-950 text-blue-300',
  PUSHING: 'bg-blue-950 text-blue-300',
  PAUSED: 'bg-ink-800 text-ink-300',
  COMPLETED: 'bg-emerald-950 text-emerald-300',
  FAILED: 'bg-rose-950 text-rose-300',
  ROLLED_BACK: 'bg-orange-950 text-orange-300',
}

const BUSY_STATES = new Set([
  'DISCOVERING',
  'PROFILING',
  'MAPPING',
  'CLEANING',
  'DEDUPLICATING',
  'VALIDATING',
  'PUSHING',
])

export function StateBadge({ state, big }: { state: MigrationState; big?: boolean }) {
  const busy = BUSY_STATES.has(state)
  return (
    <span
      className={`chip ${STATE_STYLES[state] ?? 'bg-ink-800 text-ink-300'} ${
        big ? 'px-3 py-1 text-xs' : ''
      }`}
    >
      {busy && <Loader2 className="h-3 w-3 animate-spin" />}
      {state === 'WAITING_FOR_HUMAN' && <User className="h-3 w-3" />}
      {state.replace(/_/g, ' ')}
    </span>
  )
}

const RECORD_STYLES: Record<string, string> = {
  PENDING: 'bg-ink-800 text-ink-300',
  CLEANED: 'bg-cyan-950 text-cyan-300',
  MERGED: 'bg-violet-950 text-violet-300',
  BLOCKED: 'bg-amber-950 text-amber-300',
  INVALID: 'bg-rose-950 text-rose-300',
  READY: 'bg-blue-950 text-blue-300',
  PUSHED: 'bg-emerald-950 text-emerald-300',
  FAILED: 'bg-rose-950 text-rose-300',
  ROLLED_BACK: 'bg-orange-950 text-orange-300',
}

export function RecordBadge({ status }: { status: RecordStatus }) {
  return <span className={`chip ${RECORD_STYLES[status] ?? 'bg-ink-800'}`}>{status}</span>
}

/* ------------------------------------------------------------- confidence */

export function confidenceTone(value: number) {
  if (value >= 0.9) return 'text-emerald-400'
  if (value >= 0.7) return 'text-amber-400'
  return 'text-rose-400'
}

export function ConfidenceBar({ value, label }: { value: number; label?: string }) {
  const pct = Math.round(value * 100)
  const bar = value >= 0.9 ? 'bg-emerald-500' : value >= 0.7 ? 'bg-amber-500' : 'bg-rose-500'
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-800">
        <div className={`h-full ${bar}`} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
      <span className={`font-mono text-xs ${confidenceTone(value)}`}>{pct}%</span>
      {label && <span className="text-xs text-ink-500">{label}</span>}
    </div>
  )
}

/* ------------------------------------------------------------------ actor */

export function ActorTag({ actor, aiAssisted }: { actor: string; aiAssisted?: boolean }) {
  if (actor === 'human') {
    return (
      <span className="chip bg-amber-950 text-amber-300">
        <User className="h-3 w-3" /> human
      </span>
    )
  }
  if (actor === 'target_api') {
    return <span className="chip bg-blue-950 text-blue-300">target API</span>
  }
  return (
    <span className="chip bg-ink-800 text-ink-300">
      {aiAssisted ? <Sparkles className="h-3 w-3 text-accent" /> : <Bot className="h-3 w-3" />}
      {aiAssisted ? 'agent · AI' : 'agent'}
    </span>
  )
}

/* ------------------------------------------------------------------ misc */

export function StatCard({
  label,
  value,
  hint,
  tone = 'default',
  icon: Icon,
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: 'default' | 'good' | 'warn' | 'bad'
  icon?: typeof Bot
}) {
  const tones = {
    default: 'text-white',
    good: 'text-emerald-400',
    warn: 'text-amber-400',
    bad: 'text-rose-400',
  }
  return (
    <div className="panel panel-pad">
      <div className="flex items-start justify-between">
        <div className="label">{label}</div>
        {Icon && <Icon className="h-4 w-4 text-ink-600" />}
      </div>
      <div className={`mt-2 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-500">{hint}</div>}
    </div>
  )
}

export function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-800">
        <div
          className="h-full rounded-full bg-accent transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-xs text-ink-400">
        {done} / {total || 0}
      </span>
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-14 text-center">
      <div className="text-sm font-medium text-ink-400">{title}</div>
      {hint && <div className="max-w-md text-xs text-ink-600">{hint}</div>}
    </div>
  )
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-sm font-semibold text-white">{children}</h2>
      {right}
    </div>
  )
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-12 text-ink-500">
      <Loader2 className="h-5 w-5 animate-spin" />
    </div>
  )
}
