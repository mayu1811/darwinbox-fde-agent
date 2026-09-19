import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileSpreadsheet,
  Layers,
  Sparkles,
  Upload,
  Users,
  XCircle,
} from 'lucide-react'
import type { ActivityEvent, Escalation, Migration } from '../types'
import {
  ActorTag,
  EmptyState,
  ProgressBar,
  SectionTitle,
  StatCard,
  StateBadge,
} from '../components/primitives'

function elapsed(seconds: number | null) {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const m = Math.floor(seconds / 60)
  return `${m}m ${Math.round(seconds - m * 60)}s`
}

export function Overview({
  migration,
  escalations,
  activity,
  onGoToEscalations,
}: {
  migration: Migration
  escalations: Escalation[]
  activity: ActivityEvent[]
  onGoToEscalations: () => void
}) {
  const s = migration.stats
  const open = escalations.filter((e) => e.status === 'OPEN')
  const auditFeed = activity
    .filter((a) => a.type === 'audit')
    .slice(-14)
    .reverse()

  return (
    <div className="space-y-6">
      {/* header */}
      <div className="panel panel-pad">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="font-mono text-lg font-semibold text-white">
                {migration.migration_id}
              </h1>
              <StateBadge state={migration.state} big />
              {migration.llm_provider !== 'none' && (
                <span className="chip bg-accent-soft text-accent">
                  <Sparkles className="h-3 w-3" /> {migration.llm_provider}
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-ink-400">{migration.name}</p>
          </div>
          <div className="flex gap-6 text-right text-xs">
            <div>
              <div className="label">Started</div>
              <div className="mt-1 font-mono text-ink-300">
                {migration.started_at
                  ? new Date(migration.started_at).toLocaleTimeString()
                  : '—'}
              </div>
            </div>
            <div>
              <div className="label">Elapsed</div>
              <div className="mt-1 font-mono text-ink-300">
                {elapsed(migration.elapsed_seconds)}
              </div>
            </div>
          </div>
        </div>

        <div className="mt-5">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="text-ink-300">{migration.current_step}</span>
          </div>
          <ProgressBar done={migration.progress_done} total={migration.progress_total} />
        </div>

        {migration.error && (
          <div className="mt-4 rounded-lg border border-rose-900/60 bg-rose-950/40 p-3 text-sm text-rose-300">
            {migration.error}
          </div>
        )}
      </div>

      {/* attention banner */}
      {open.length > 0 && (
        <button
          onClick={onGoToEscalations}
          className="flex w-full items-center gap-3 rounded-xl border border-amber-800/60 bg-amber-950/30 p-4 text-left transition-colors hover:bg-amber-950/50"
        >
          <AlertTriangle className="h-5 w-5 shrink-0 text-amber-400" />
          <div className="flex-1">
            <div className="text-sm font-medium text-amber-200">
              {open.length} escalation{open.length > 1 ? 's' : ''} need your decision
            </div>
            <div className="text-xs text-amber-400/70">
              The agent finished everything it could decide on its own and is waiting.
            </div>
          </div>
          <span className="btn-ghost border-amber-800/60 text-amber-200">Review now</span>
        </button>
      )}

      {/* stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="Files"
          value={s.files ?? 0}
          hint={`${s.source_rows ?? 0} source rows`}
          icon={FileSpreadsheet}
        />
        <StatCard
          label="Records"
          value={(s.source_rows ?? 0) - (s.duplicates_merged ?? 0)}
          hint={`${s.duplicates_merged ?? 0} duplicates reconciled`}
          icon={Users}
        />
        <StatCard
          label="Auto-resolved"
          value={s.auto_resolved ?? 0}
          hint={`${s.values_cleaned ?? 0} values cleaned`}
          tone="good"
          icon={CheckCircle2}
        />
        <StatCard
          label="Escalations"
          value={s.escalations_total ?? 0}
          hint={`${open.length} still open`}
          tone={open.length ? 'warn' : 'default'}
          icon={AlertTriangle}
        />
        <StatCard
          label="Pushed"
          value={s.pushed ?? 0}
          hint={`${s.ready ?? 0} ready to push`}
          tone="good"
          icon={Database}
        />
        <StatCard
          label="Failures"
          value={s.failed ?? 0}
          hint={s.rolled_back ? `${s.rolled_back} rolled back` : 'target rejections'}
          tone={s.failed ? 'bad' : 'default'}
          icon={XCircle}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* autonomy split */}
        <div className="panel panel-pad lg:col-span-2">
          <SectionTitle>Autonomy split</SectionTitle>
          <p className="mb-4 text-xs leading-relaxed text-ink-500">
            What the agent handled by itself versus what it brought to you.
          </p>
          <AutonomyRow
            label="Field mappings applied automatically"
            value={s.fields_auto_mapped ?? 0}
            total={(s.fields_auto_mapped ?? 0) + (s.fields_escalated ?? 0)}
          />
          <AutonomyRow
            label="Values cleaned deterministically"
            value={s.values_cleaned ?? 0}
            total={s.values_cleaned ?? 0}
          />
          <AutonomyRow
            label="Duplicates merged without a human"
            value={s.duplicates_merged ?? 0}
            total={(s.duplicates_merged ?? 0) + (s.duplicate_conflicts ?? 0)}
          />
          <AutonomyRow
            label="Columns left unmapped (not guessed)"
            value={s.fields_ignored ?? 0}
            total={s.fields_ignored ?? 0}
            neutral
          />
          <div className="mt-4 rounded-lg border border-ink-800 bg-ink-950/60 p-3 text-xs leading-relaxed text-ink-400">
            <span className="font-medium text-ink-200">
              {s.escalations_total ?? 0} human decision
              {(s.escalations_total ?? 0) === 1 ? '' : 's'}
            </span>{' '}
            out of {(s.auto_resolved ?? 0) + (s.escalations_total ?? 0)} total decisions —
            everything else was deterministic, reversible, or high-confidence.
          </div>
        </div>

        {/* files */}
        <div className="panel panel-pad lg:col-span-3">
          <SectionTitle>Source files</SectionTitle>
          <div className="space-y-2">
            {migration.files.map((file) => (
              <div
                key={file.id}
                className="flex items-center gap-3 rounded-lg border border-ink-800 bg-ink-950/50 p-3"
              >
                <div className="rounded-md bg-ink-850 p-2">
                  {file.file_type === 'csv' ? (
                    <FileSpreadsheet className="h-4 w-4 text-ink-400" />
                  ) : (
                    <Layers className="h-4 w-4 text-ink-400" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-white">{file.filename}</div>
                  <div className="text-xs text-ink-500">
                    {file.row_count} rows · {file.column_count} columns ·{' '}
                    {(file.size_bytes / 1024).toFixed(1)} KB
                  </div>
                </div>
                <span className="chip bg-ink-850 text-ink-400 uppercase">{file.file_type}</span>
              </div>
            ))}
            {migration.files.length === 0 && (
              <EmptyState title="No source files" hint="Start a demo migration to load them." />
            )}
          </div>

          <SectionTitle>
            <span className="mt-6 block">Live activity</span>
          </SectionTitle>
          <div className="max-h-64 space-y-1.5 overflow-y-auto pr-1">
            {auditFeed.length === 0 && (
              <div className="py-6 text-center text-xs text-ink-600">
                Waiting for the agent…
              </div>
            )}
            {auditFeed.map((event) => (
              <div
                key={event.seq}
                className="flex animate-fade-in items-start gap-2.5 rounded-md px-2 py-1.5 text-xs hover:bg-ink-850/60"
              >
                <span className="mt-0.5 shrink-0">
                  <ActorTag
                    actor={event.payload.actor}
                    aiAssisted={event.payload.ai_assisted}
                  />
                </span>
                <span className="min-w-0 flex-1 leading-relaxed text-ink-300">
                  {event.payload.summary}
                </span>
                <span className="shrink-0 font-mono text-[10px] text-ink-600">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function AutonomyRow({
  label,
  value,
  total,
  neutral,
}: {
  label: string
  value: number
  total: number
  neutral?: boolean
}) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="mb-3">
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-ink-400">{label}</span>
        <span className="font-mono text-ink-300">
          {value}
          {total !== value && <span className="text-ink-600"> / {total}</span>}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-800">
        <div
          className={`h-full rounded-full ${neutral ? 'bg-ink-600' : 'bg-emerald-500'}`}
          style={{ width: `${total > 0 ? Math.max(pct, 3) : 0}%` }}
        />
      </div>
    </div>
  )
}

export function NoMigration({
  onStartDemo,
  onUpload,
  busy,
}: {
  onStartDemo: () => void
  onUpload: (files: FileList) => void
  busy: boolean
}) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center">
      <div className="panel max-w-xl p-10 text-center">
        <div className="mx-auto mb-5 w-fit rounded-xl bg-accent-soft p-3">
          <Database className="h-6 w-6 text-accent" />
        </div>
        <h1 className="text-xl font-semibold text-white">AI Data Migration Agent</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-400">
          Two messy source files, one target schema. The agent maps, cleans, de-duplicates and
          validates on its own — and stops only where a wrong answer would be expensive.
        </p>
        <div className="mt-7 flex flex-col items-center gap-3">
          <button onClick={onStartDemo} disabled={busy} className="btn-primary w-64 justify-center">
            {busy ? 'Starting…' : 'Run demo migration'}
          </button>
          <label className="btn-ghost w-64 cursor-pointer justify-center">
            <Upload className="h-4 w-4" />
            Upload your own CSV / XLSX
            <input
              type="file"
              multiple
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={(e) => e.target.files && onUpload(e.target.files)}
            />
          </label>
        </div>
        <p className="mt-6 text-xs text-ink-600">
          Runs fully offline in demo mode — no API key required.
        </p>
      </div>
    </div>
  )
}
