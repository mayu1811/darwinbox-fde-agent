import { useCallback, useEffect, useRef, useState } from 'react'
import { api, activityStreamUrl } from '../services/api'
import type { ActivityEvent, Escalation, Migration } from '../types'

const ACTIVE_STATES = new Set([
  'DISCOVERING',
  'PROFILING',
  'MAPPING',
  'CLEANING',
  'DEDUPLICATING',
  'VALIDATING',
  'PUSHING',
])

/**
 * Live view of one migration.
 *
 * SSE drives the activity feed and gives instant feedback; a slow poll keeps
 * the authoritative record (button enablement, stats) correct even if the
 * stream drops. The UI is never the source of truth - the backend is.
 */
export function useMigration(migrationId: string | null) {
  const [migration, setMigration] = useState<Migration | null>(null)
  const [escalations, setEscalations] = useState<Escalation[]>([])
  const [activity, setActivity] = useState<ActivityEvent[]>([])
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const sourceRef = useRef<EventSource | null>(null)

  const refresh = useCallback(async () => {
    if (!migrationId) return
    try {
      const [m, e] = await Promise.all([
        api.getMigration(migrationId),
        api.escalations(migrationId),
      ])
      setMigration(m)
      setEscalations(e)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load migration')
    }
  }, [migrationId])

  // Initial load
  useEffect(() => {
    if (!migrationId) {
      setMigration(null)
      setEscalations([])
      setActivity([])
      return
    }
    setLoading(true)
    refresh().finally(() => setLoading(false))
  }, [migrationId, refresh])

  // Live activity stream
  useEffect(() => {
    if (!migrationId) return
    setActivity([])
    const source = new EventSource(activityStreamUrl(migrationId))
    sourceRef.current = source

    const onMessage = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data) as ActivityEvent
        setActivity((prev) => {
          if (prev.some((p) => p.seq === parsed.seq)) return prev
          return [...prev, parsed].slice(-400)
        })
        if (parsed.type === 'state' || parsed.type === 'escalation') {
          void refresh()
        }
      } catch {
        /* ignore malformed frame */
      }
    }

    ;['state', 'audit', 'escalation', 'push', 'rollback'].forEach((name) =>
      source.addEventListener(name, onMessage as EventListener),
    )
    source.onopen = () => setConnected(true)
    source.onerror = () => setConnected(false)

    return () => {
      source.close()
      sourceRef.current = null
      setConnected(false)
    }
  }, [migrationId, refresh])

  // Safety-net poll while the agent is working
  useEffect(() => {
    if (!migrationId) return
    const active = migration && ACTIVE_STATES.has(migration.state)
    const interval = window.setInterval(() => void refresh(), active ? 1200 : 5000)
    return () => window.clearInterval(interval)
  }, [migrationId, migration, refresh])

  return { migration, escalations, activity, connected, loading, error, refresh }
}
