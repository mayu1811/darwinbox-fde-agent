"""Request / response models. Keeps the ORM out of the HTTP layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CreateMigrationRequest(BaseModel):
    name: str = Field(default="Employee migration", max_length=160)
    use_demo_data: bool = True
    auto_start: bool = True


class SourceFileOut(ORMModel):
    id: int
    filename: str
    file_type: str
    size_bytes: int
    row_count: int
    column_count: int
    inferred_schema: dict = {}


class MigrationSummary(ORMModel):
    migration_id: str
    name: str
    entity: str
    state: str
    current_step: str
    progress_total: int
    progress_done: int
    mode: str
    llm_provider: str
    error: str | None = None
    stats: dict = {}
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MigrationDetail(MigrationSummary):
    files: list[SourceFileOut] = []
    elapsed_seconds: float | None = None
    open_escalations: int = 0
    can_start: bool = False
    can_pause: bool = False
    can_resume: bool = False
    can_push: bool = False
    can_retry: bool = False
    can_rollback: bool = False


class FieldMappingOut(ORMModel):
    id: int
    source_file_name: str
    source_field: str
    target_field: str | None
    confidence: float
    margin: float
    method: str
    ai_assisted: bool
    reason: str
    candidates: list = []
    sample_values: list = []
    decision: str
    resolved_by: str | None = None


class RecordOut(ORMModel):
    id: int
    source_file_name: str
    source_row_number: int
    employee_id: str | None
    raw: dict = {}
    transformed: dict = {}
    changes: list = []
    validation_errors: list = []
    status: str
    is_duplicate: bool
    merged_into_id: int | None = None
    merged_from: list = []
    dedupe_notes: list = []
    push_status: str | None = None
    push_error: str | None = None
    push_failure_kind: str | None = None
    push_attempt_count: int = 0
    repair_attempts: int = 0


class EscalationOut(ORMModel):
    id: int
    type: str
    severity: str
    title: str
    source_file: str | None
    source_field: str | None
    source_value: str | None
    candidate_values: list = []
    sample_values: list = []
    record_id: str | None
    affected_record_ids: list = []
    reason: str
    agent_recommendation: str | None = None
    confidence: float
    blocking: bool
    status: str
    resolution: dict | None = None
    resolved_by: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class EscalationResolveRequest(BaseModel):
    decision: Literal["APPROVED", "CORRECTED", "REJECTED"] = "APPROVED"
    value: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)
    resolved_by: str = Field(default="implementation_consultant", max_length=64)


class AuditEventOut(ORMModel):
    id: int
    event: str
    actor: str
    actor_name: str | None
    summary: str
    reason: str | None
    record_ref: str | None
    before: dict | None
    after: dict | None
    details: dict = {}
    confidence: float | None
    ai_assisted: bool
    created_at: datetime


class PushAttemptOut(ORMModel):
    id: int
    employee_id: str
    attempt: int
    status: str
    failure_kind: str | None
    error: str | None
    target_response: dict = {}
    created_at: datetime


class TargetEmployeeOut(ORMModel):
    employee_id: str
    migration_ref: str | None
    payload: dict
    created_at: datetime


class ActivityEvent(BaseModel):
    seq: int
    type: str
    migration_id: str
    timestamp: str
    payload: dict[str, Any]


class HealthOut(BaseModel):
    status: str
    app: str
    environment: str
    llm: dict
    autonomy: dict
    target_schema_version: str
