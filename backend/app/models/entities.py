"""Persistent model of a migration run.

The whole agent is a state machine over these tables - there is no hidden
in-memory state, which is what makes the run auditable and resumable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import EscalationStatus, MappingDecision, MigrationState, RecordStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Migration(Base):
    __tablename__ = "migrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), default="Employee migration")
    entity: Mapped[str] = mapped_column(String(64), default="employee")
    state: Mapped[str] = mapped_column(String(32), default=MigrationState.CREATED, index=True)
    current_step: Mapped[str] = mapped_column(String(120), default="Not started")
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String(32), default="demo")  # demo | upload
    llm_provider: Mapped[str] = mapped_column(String(32), default="none")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    files: Mapped[list["SourceFile"]] = relationship(
        back_populates="migration", cascade="all, delete-orphan"
    )
    records: Mapped[list["EmployeeRecord"]] = relationship(
        back_populates="migration", cascade="all, delete-orphan"
    )
    mappings: Mapped[list["FieldMapping"]] = relationship(
        back_populates="migration", cascade="all, delete-orphan"
    )
    escalations: Mapped[list["Escalation"]] = relationship(
        back_populates="migration", cascade="all, delete-orphan"
    )


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(ForeignKey("migrations.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    column_count: Mapped[int] = mapped_column(Integer, default=0)
    # Output of schema_inference - per column: dtype, null ratio, samples, ...
    inferred_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    migration: Mapped[Migration] = relationship(back_populates="files")
    records: Mapped[list["SourceRecord"]] = relationship(
        back_populates="source_file", cascade="all, delete-orphan"
    )


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(ForeignKey("migrations.id", ondelete="CASCADE"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    row_number: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    source_file: Mapped[SourceFile] = relationship(back_populates="records")


class FieldMapping(Base):
    __tablename__ = "field_mappings"
    __table_args__ = (UniqueConstraint("migration_id", "source_file_id", "source_field"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(ForeignKey("migrations.id", ondelete="CASCADE"))
    source_file_id: Mapped[int] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    source_file_name: Mapped[str] = mapped_column(String(255))
    source_field: Mapped[str] = mapped_column(String(255))
    target_field: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    margin: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(48), default="deterministic_alias")
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    # [{target_field, confidence, reason}, ...] ordered best-first
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    sample_values: Mapped[list] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(32), default=MappingDecision.AUTO_APPLIED)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    migration: Mapped[Migration] = relationship(back_populates="mappings")


class EmployeeRecord(Base):
    """One prospective row in the target platform."""

    __tablename__ = "employee_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(ForeignKey("migrations.id", ondelete="CASCADE"))
    source_file_name: Mapped[str] = mapped_column(String(255))
    source_row_number: Mapped[int] = mapped_column(Integer, default=0)
    source_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    employee_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    mapped: Mapped[dict] = mapped_column(JSON, default=dict)       # after mapping, before cleaning
    transformed: Mapped[dict] = mapped_column(JSON, default=dict)  # target-shaped payload
    changes: Mapped[list] = mapped_column(JSON, default=list)      # [{field, before, after, rule}]
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(24), default=RecordStatus.PENDING, index=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merged_from: Mapped[list] = mapped_column(JSON, default=list)   # provenance of merged rows
    dedupe_notes: Mapped[list] = mapped_column(JSON, default=list)

    push_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    push_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_failure_kind: Mapped[str | None] = mapped_column(String(24), nullable=True)
    push_attempt_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    migration: Mapped[Migration] = relationship(back_populates="records")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(ForeignKey("migrations.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    title: Mapped[str] = mapped_column(String(200), default="")
    source_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_field: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{value, label, confidence, reason, ...}]
    candidate_values: Mapped[list] = mapped_column(JSON, default=list)
    sample_values: Mapped[list] = mapped_column(JSON, default=list)
    record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Internal EmployeeRecord ids affected by this escalation.
    affected_record_ids: Mapped[list] = mapped_column(JSON, default=list)
    field_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    agent_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default=EscalationStatus.OPEN, index=True)
    resolution: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    migration: Mapped[Migration] = relationship(back_populates="escalations")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(
        ForeignKey("migrations.id", ondelete="CASCADE"), index=True
    )
    migration_ref: Mapped[str] = mapped_column(String(32), index=True)
    event: Mapped[str] = mapped_column(String(48), index=True)
    actor: Mapped[str] = mapped_column(String(24), default="agent", index=True)
    actor_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PushAttempt(Base):
    __tablename__ = "push_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_id: Mapped[int] = mapped_column(
        ForeignKey("migrations.id", ondelete="CASCADE"), index=True
    )
    migration_ref: Mapped[str] = mapped_column(String(32), index=True)
    employee_record_id: Mapped[int] = mapped_column(Integer, index=True)
    employee_id: Mapped[str] = mapped_column(String(64), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16))
    failure_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    target_response: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TargetEmployee(Base):
    """Store behind the *mock* target platform API.

    Deliberately a separate table: the agent must go through the service
    boundary rather than writing here directly.
    """

    __tablename__ = "target_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    migration_ref: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TargetCallLog(Base):
    """Every call the agent makes into the mock target platform."""

    __tablename__ = "target_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    migration_ref: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
