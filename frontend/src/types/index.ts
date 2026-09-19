export type MigrationState =
  | 'CREATED'
  | 'DISCOVERING'
  | 'PROFILING'
  | 'MAPPING'
  | 'CLEANING'
  | 'DEDUPLICATING'
  | 'VALIDATING'
  | 'WAITING_FOR_HUMAN'
  | 'READY_TO_PUSH'
  | 'PUSHING'
  | 'PAUSED'
  | 'COMPLETED'
  | 'FAILED'
  | 'ROLLED_BACK'

export interface MigrationStats {
  files?: number
  source_rows?: number
  records?: number
  fields_mapped?: number
  fields_auto_mapped?: number
  fields_escalated?: number
  fields_ignored?: number
  values_cleaned?: number
  duplicates_found?: number
  duplicates_merged?: number
  auto_resolved?: number
  escalations_total?: number
  escalations_open?: number
  ready?: number
  invalid?: number
  blocked?: number
  pushed?: number
  failed?: number
  rolled_back?: number
  ai_assisted_decisions?: number
  [key: string]: number | undefined
}

export interface SourceFile {
  id: number
  filename: string
  file_type: string
  size_bytes: number
  row_count: number
  column_count: number
  inferred_schema: Record<string, ColumnProfile>
}

export interface ColumnProfile {
  name: string
  key: string
  semantic_type: string
  type_confidence: number
  count: number
  non_empty: number
  null_ratio: number
  distinct: number
  unique_ratio: number
  samples: string[]
  has_leading_trailing_space: boolean
  day_first?: boolean
  signals: Record<string, number>
}

export interface Migration {
  migration_id: string
  name: string
  entity: string
  state: MigrationState
  current_step: string
  progress_total: number
  progress_done: number
  mode: string
  llm_provider: string
  error: string | null
  stats: MigrationStats
  created_at: string
  started_at: string | null
  completed_at: string | null
  files: SourceFile[]
  elapsed_seconds: number | null
  open_escalations: number
  can_start: boolean
  can_pause: boolean
  can_resume: boolean
  can_push: boolean
  can_retry: boolean
  can_rollback: boolean
}

export interface MappingCandidate {
  target_field: string
  confidence: number
  reason: string
  method: string
  matched_alias: string | null
  name_similarity: number
  type_compatible: boolean
  ai_assisted: boolean
}

export interface FieldMapping {
  id: number
  source_file_name: string
  source_field: string
  target_field: string | null
  confidence: number
  margin: number
  method: string
  ai_assisted: boolean
  reason: string
  candidates: MappingCandidate[]
  sample_values: string[]
  decision: 'AUTO_APPLIED' | 'ESCALATED' | 'HUMAN_RESOLVED' | 'IGNORED'
  resolved_by: string | null
}

export interface RecordChange {
  field: string
  before: string | null
  after: string | null
  rule: string
  reversible: boolean
  actor: 'agent' | 'human'
}

export interface ValidationError {
  field: string
  code: string
  message: string
  value: string | null
  repairable: boolean
}

export type RecordStatus =
  | 'PENDING'
  | 'CLEANED'
  | 'MERGED'
  | 'BLOCKED'
  | 'INVALID'
  | 'READY'
  | 'PUSHED'
  | 'FAILED'
  | 'ROLLED_BACK'

export interface EmployeeRecord {
  id: number
  source_file_name: string
  source_row_number: number
  employee_id: string | null
  raw: Record<string, string>
  transformed: Record<string, string | null>
  changes: RecordChange[]
  validation_errors: ValidationError[]
  status: RecordStatus
  is_duplicate: boolean
  merged_into_id: number | null
  merged_from: { source_file: string; row: number; record_id: number }[]
  dedupe_notes: string[]
  push_status: string | null
  push_error: string | null
  push_failure_kind: string | null
  push_attempt_count: number
  repair_attempts: number
}

export interface EscalationCandidate {
  value: string
  label: string
  confidence: number
  reason: string
}

export type EscalationType =
  | 'AMBIGUOUS_MAPPING'
  | 'MISSING_MANDATORY_FIELD'
  | 'UNSAFE_VALUE'
  | 'VALIDATION_FAILURE'
  | 'DUPLICATE_CONFLICT'
  | 'DESTRUCTIVE_ACTION'

export interface Escalation {
  id: number
  type: EscalationType
  severity: 'LOW' | 'MEDIUM' | 'HIGH'
  title: string
  source_file: string | null
  source_field: string | null
  source_value: string | null
  candidate_values: EscalationCandidate[]
  sample_values: string[]
  record_id: string | null
  affected_record_ids: number[]
  reason: string
  agent_recommendation: string | null
  confidence: number
  blocking: boolean
  status: 'OPEN' | 'APPROVED' | 'CORRECTED' | 'REJECTED'
  resolution: { decision: string; value: string | null; note: string | null } | null
  resolved_by: string | null
  created_at: string
  resolved_at: string | null
}

export interface AuditEvent {
  id: number
  event: string
  actor: 'agent' | 'human' | 'system' | 'target_api'
  actor_name: string | null
  summary: string
  reason: string | null
  record_ref: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  details: Record<string, unknown>
  confidence: number | null
  ai_assisted: boolean
  created_at: string
}

export interface PushAttempt {
  id: number
  employee_id: string
  attempt: number
  status: string
  failure_kind: string | null
  error: string | null
  target_response: Record<string, unknown>
  created_at: string
}

export interface ActivityEvent {
  seq: number
  type: 'state' | 'audit' | 'escalation' | 'push' | 'rollback'
  migration_id: string
  timestamp: string
  payload: Record<string, any>
}

export interface Health {
  status: string
  app: string
  environment: string
  llm: {
    enabled: boolean
    provider: string
    reachable: boolean
    mode: string
    model?: string
  }
  autonomy: {
    high_confidence_threshold: number
    medium_confidence_threshold: number
    min_confidence_margin: number
    max_auto_repair_attempts: number
    max_push_attempts: number
  }
  target_schema_version: string
}

export interface TargetEmployee {
  employee_id: string
  migration_ref: string | null
  payload: Record<string, string>
  created_at: string
}
