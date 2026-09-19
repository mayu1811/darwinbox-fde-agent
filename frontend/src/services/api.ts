import type {
  AuditEvent,
  Escalation,
  FieldMapping,
  Health,
  Migration,
  EmployeeRecord,
  PushAttempt,
  TargetEmployee,
} from '../types'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export class ApiError extends Error {
  code: string
  status: number
  constructor(message: string, code: string, status: number) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new ApiError(
      'Cannot reach the backend. Is uvicorn running on port 8000?',
      'network_error',
      0,
    )
  }

  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let code = 'http_error'
    try {
      const body = await response.json()
      if (body?.error) {
        message = body.error.message ?? message
        code = body.error.code ?? code
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, code, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/api/health'),
  targetSchema: () => request<Record<string, any>>('/api/target-schema'),
  targetMeta: () => request<Record<string, any>>('/target/meta'),

  listMigrations: () => request<Migration[]>('/api/migrations'),
  createDemoMigration: (name = 'Acme Corp — employee migration') =>
    request<Migration>('/api/migrations', {
      method: 'POST',
      body: JSON.stringify({ name, use_demo_data: true, auto_start: true }),
    }),
  uploadMigration: (files: File[], name: string) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<Migration>(
      `/api/migrations/upload?name=${encodeURIComponent(name)}&auto_start=true`,
      { method: 'POST', body: form, headers: {} },
    )
  },
  getMigration: (id: string) => request<Migration>(`/api/migrations/${id}`),
  start: (id: string) => request<Migration>(`/api/migrations/${id}/start`, { method: 'POST' }),
  pause: (id: string) => request<Migration>(`/api/migrations/${id}/pause`, { method: 'POST' }),
  resume: (id: string) => request<Migration>(`/api/migrations/${id}/resume`, { method: 'POST' }),
  push: (id: string) => request<Migration>(`/api/migrations/${id}/push`, { method: 'POST' }),
  retry: (id: string) => request<Migration>(`/api/migrations/${id}/retry`, { method: 'POST' }),
  rollback: (id: string) =>
    request<Migration>(`/api/migrations/${id}/rollback`, { method: 'POST' }),

  mappings: (id: string) => request<FieldMapping[]>(`/api/migrations/${id}/mappings`),
  records: (id: string, filter = 'all') =>
    request<EmployeeRecord[]>(`/api/migrations/${id}/records?filter=${filter}`),
  escalations: (id: string) => request<Escalation[]>(`/api/migrations/${id}/escalations`),
  audit: (id: string, params: { actor?: string; category?: string; q?: string } = {}) => {
    const search = new URLSearchParams()
    if (params.actor) search.set('actor', params.actor)
    if (params.category) search.set('category', params.category)
    if (params.q) search.set('q', params.q)
    const qs = search.toString()
    return request<AuditEvent[]>(`/api/migrations/${id}/audit${qs ? `?${qs}` : ''}`)
  },
  pushAttempts: (id: string) =>
    request<PushAttempt[]>(`/api/migrations/${id}/push-attempts`),
  targetEmployees: (id?: string) =>
    request<TargetEmployee[]>(`/target/employees${id ? `?migration_id=${id}` : ''}`),

  resolveEscalation: (
    escalationId: number,
    body: { decision: string; value?: string | null; note?: string | null },
  ) =>
    request<{ agent_resumed: boolean; open_escalations: number }>(
      `/api/escalations/${escalationId}/resolve`,
      { method: 'POST', body: JSON.stringify({ resolved_by: 'implementation_consultant', ...body }) },
    ),

  resetDemo: () => request<{ status: string }>('/api/demo/reset', { method: 'POST' }),
}

export function activityStreamUrl(id: string) {
  return `${BASE}/api/migrations/${id}/activity`
}
