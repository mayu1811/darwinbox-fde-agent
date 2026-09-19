import { useCallback, useEffect, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  Database,
  GitCompareArrows,
  LayoutDashboard,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  ScrollText,
  Sparkles,
  Table2,
  Upload,
  Undo2,
} from 'lucide-react'
import { api, ApiError } from './services/api'
import { useMigration } from './hooks/useMigration'
import { ToastProvider, useToast } from './hooks/useToast'
import type { Health } from './types'
import { Overview, NoMigration } from './pages/Overview'
import { AgentActivity } from './pages/AgentActivity'
import { Escalations } from './pages/Escalations'
import { Mappings } from './pages/Mappings'
import { DataPreview } from './pages/DataPreview'
import { TargetPush } from './pages/TargetPush'
import { AuditTrail } from './pages/AuditTrail'
import { StateBadge } from './components/primitives'
import { ConfirmDialog } from './components/ConfirmDialog'
import type { ConfirmRequest } from './components/ConfirmDialog'

type Tab = 'overview' | 'activity' | 'escalations' | 'mappings' | 'data' | 'target' | 'audit'

const NAV: { key: Tab; label: string; icon: typeof Activity }[] = [
  { key: 'overview', label: 'Migration overview', icon: LayoutDashboard },
  { key: 'activity', label: 'Agent activity', icon: Activity },
  { key: 'escalations', label: 'Escalations', icon: AlertTriangle },
  { key: 'mappings', label: 'Field mappings', icon: GitCompareArrows },
  { key: 'data', label: 'Data preview', icon: Table2 },
  { key: 'target', label: 'Target push', icon: Database },
  { key: 'audit', label: 'Audit trail', icon: ScrollText },
]

function Shell() {
  const { toast } = useToast()
  const [migrationId, setMigrationId] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('overview')
  const [health, setHealth] = useState<Health | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null)

  const { migration, escalations, activity, connected, error, refresh } =
    useMigration(migrationId)

  // Find the most recent migration on load so a refresh does not lose the demo.
  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => toast('Backend is unreachable — is uvicorn running?', 'error'))
    api
      .listMigrations()
      .then((list) => {
        if (list.length > 0) setMigrationId(list[0].migration_id)
      })
      .catch(() => {})
  }, [toast])

  const run = useCallback(
    async (label: string, fn: () => Promise<unknown>, success?: string) => {
      setBusy(true)
      try {
        await fn()
        if (success) toast(success, 'success')
      } catch (err) {
        const message = err instanceof ApiError ? err.message : `${label} failed`
        toast(message, 'error')
      } finally {
        setBusy(false)
        await refresh()
      }
    },
    [refresh, toast],
  )

  const startDemo = () =>
    run(
      'Start demo',
      async () => {
        const created = await api.createDemoMigration()
        setMigrationId(created.migration_id)
        setTab('overview')
      },
      'Demo migration started — watch the agent work',
    )

  const upload = (files: FileList) =>
    run(
      'Upload',
      async () => {
        const created = await api.uploadMigration(Array.from(files), 'Uploaded employee data')
        setMigrationId(created.migration_id)
        setTab('overview')
      },
      'Files uploaded — the agent has started',
    )

  const resolve = async (
    id: number,
    body: { decision: string; value?: string | null; note?: string | null },
  ) => {
    try {
      const result = await api.resolveEscalation(id, body)
      toast(
        result.agent_resumed
          ? 'Decision applied — the agent resumed automatically'
          : `Decision applied — ${result.open_escalations} escalation(s) still open`,
        'success',
      )
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Could not apply the decision', 'error')
    } finally {
      await refresh()
    }
  }

  const rollback = () =>
    setConfirmRequest({
      title: `Roll back ${migration?.migration_id}?`,
      body: `This deletes all ${migration?.stats.pushed ?? 0} record(s) this migration wrote to the target platform.`,
      consequence:
        'Records that were already in the target before this migration are not touched - every push is tagged with the migration id, so the rollback is exact. The migration itself stays in the audit trail.',
      confirmLabel: 'Roll back',
      destructive: true,
      onConfirm: async () => {
        await run('Rollback', () => api.rollback(migrationId!), 'Rollback complete')
        setConfirmRequest(null)
      },
    })

  const reset = () =>
    setConfirmRequest({
      title: 'Reset the demo?',
      body: 'Deletes every migration, its audit trail, and everything in the mock target platform.',
      consequence: 'Source files on disk are not affected. Use this to replay the demo from scratch.',
      confirmLabel: 'Reset everything',
      destructive: true,
      onConfirm: async () => {
        await run(
          'Reset',
          async () => {
            await api.resetDemo()
            setMigrationId(null)
          },
          'Demo reset',
        )
        setConfirmRequest(null)
      },
    })

  const openCount = escalations.filter((e) => e.status === 'OPEN').length

  return (
    <div className="flex h-screen overflow-hidden bg-ink-950">
      {/* sidebar */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-ink-800 bg-ink-900/50">
        <div className="border-b border-ink-800 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="rounded-lg bg-accent-soft p-1.5">
              <Database className="h-4 w-4 text-accent" />
            </div>
            <div>
              <div className="text-sm font-semibold leading-tight text-white">
                Migration Agent
              </div>
              <div className="text-[10px] uppercase tracking-wider text-ink-600">
                Darwinbox FDE
              </div>
            </div>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {NAV.map((item) => {
            const Icon = item.icon
            const active = tab === item.key
            return (
              <button
                key={item.key}
                onClick={() => setTab(item.key)}
                disabled={!migration}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors disabled:opacity-30 ${
                  active
                    ? 'bg-accent-soft font-medium text-white'
                    : 'text-ink-400 hover:bg-ink-850 hover:text-ink-200'
                }`}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="flex-1 text-left">{item.label}</span>
                {item.key === 'escalations' && openCount > 0 && (
                  <span className="chip bg-amber-500 text-ink-950">{openCount}</span>
                )}
              </button>
            )
          })}
        </nav>

        <div className="space-y-2 border-t border-ink-800 p-3">
          {health && (
            <div className="rounded-lg border border-ink-800 bg-ink-950/60 p-2.5 text-[11px]">
              <div className="mb-1 flex items-center gap-1.5">
                <Sparkles
                  className={`h-3 w-3 ${health.llm.enabled && health.llm.reachable ? 'text-accent' : 'text-ink-600'}`}
                />
                <span className="font-medium text-ink-300">
                  {health.llm.enabled && health.llm.reachable ? 'LLM-assisted' : 'Demo mode'}
                </span>
              </div>
              <p className="leading-relaxed text-ink-600">
                {health.llm.enabled && health.llm.reachable
                  ? `${health.llm.provider} · ${health.llm.model}`
                  : 'Deterministic rules + confidence scoring. No API key needed.'}
              </p>
            </div>
          )}
          <button onClick={reset} disabled={busy} className="btn-ghost w-full justify-center">
            <RotateCcw className="h-3.5 w-3.5" />
            Reset demo
          </button>
        </div>
      </aside>

      {/* main */}
      <main className="flex min-w-0 flex-1 flex-col">
        {migration && (
          <header className="flex flex-wrap items-center gap-3 border-b border-ink-800 bg-ink-900/40 px-6 py-3">
            <span className="font-mono text-sm text-white">{migration.migration_id}</span>
            <StateBadge state={migration.state} />
            <span className="hidden truncate text-xs text-ink-500 md:block">
              {migration.current_step}
            </span>

            <div className="ml-auto flex flex-wrap items-center gap-2">
              <button
                onClick={() => void run('Start', () => api.start(migrationId!), 'Agent started')}
                disabled={busy || !migration.can_start}
                className="btn-ghost"
              >
                <Play className="h-3.5 w-3.5" /> Start
              </button>
              <button
                onClick={() => void run('Pause', () => api.pause(migrationId!), 'Pausing…')}
                disabled={busy || !migration.can_pause}
                className="btn-ghost"
              >
                <Pause className="h-3.5 w-3.5" /> Pause
              </button>
              <button
                onClick={() => void run('Resume', () => api.resume(migrationId!), 'Agent resumed')}
                disabled={busy || !migration.can_resume}
                className="btn-ghost"
              >
                <Play className="h-3.5 w-3.5" /> Resume
              </button>
              <button
                onClick={() => void run('Push', () => api.push(migrationId!), 'Push started')}
                disabled={busy || !migration.can_push}
                className="btn-ghost"
              >
                <Upload className="h-3.5 w-3.5" /> Push
              </button>
              <button
                onClick={() =>
                  void run('Retry', () => api.retry(migrationId!), 'Retrying failed records')
                }
                disabled={busy || !migration.can_retry}
                className="btn-ghost"
              >
                <RefreshCw className="h-3.5 w-3.5" /> Retry failed
              </button>
              <button
                onClick={rollback}
                disabled={busy || !migration.can_rollback}
                className="btn-danger"
              >
                <Undo2 className="h-3.5 w-3.5" /> Rollback
              </button>
            </div>
          </header>
        )}

        <div className="flex-1 overflow-y-auto p-6">
          {error && (
            <div className="mb-4 rounded-lg border border-rose-900/60 bg-rose-950/40 p-3 text-sm text-rose-300">
              {error}
            </div>
          )}

          {!migration ? (
            <NoMigration onStartDemo={startDemo} onUpload={upload} busy={busy} />
          ) : tab === 'overview' ? (
            <Overview
              migration={migration}
              escalations={escalations}
              activity={activity}
              onGoToEscalations={() => setTab('escalations')}
            />
          ) : tab === 'activity' ? (
            <AgentActivity migration={migration} activity={activity} connected={connected} />
          ) : tab === 'escalations' ? (
            <Escalations escalations={escalations} onResolve={resolve} />
          ) : tab === 'mappings' ? (
            <Mappings migrationId={migration.migration_id} />
          ) : tab === 'data' ? (
            <DataPreview migrationId={migration.migration_id} />
          ) : tab === 'target' ? (
            <TargetPush migrationId={migration.migration_id} />
          ) : (
            <AuditTrail migrationId={migration.migration_id} />
          )}
        </div>
      </main>

      <ConfirmDialog
        request={confirmRequest}
        busy={busy}
        onClose={() => setConfirmRequest(null)}
      />
    </div>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Shell />
    </ToastProvider>
  )
}
