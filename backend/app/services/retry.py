"""Pushing records to the target, with bounded exponential-backoff retry.

Transient failures are retried automatically - that is routine work, not a
decision. Permanent failures (the target rejected the data) are NOT retried:
retrying a 422 is just a slower 422, and the record is surfaced to the human
instead.
"""
from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    Actor,
    AuditEventType,
    EmployeeRecord,
    FailureKind,
    Migration,
    PushAttempt,
    RecordStatus,
)
from . import audit, target_api
from .events import bus


def build_payload(record: EmployeeRecord) -> dict:
    """Target-shaped payload, dropping empty optional fields."""
    return {k: v for k, v in (record.transformed or {}).items() if v not in (None, "")}


def _idempotency_key(migration: Migration, record: EmployeeRecord) -> str:
    return f"{migration.migration_id}:{record.employee_id}"


async def push_record(
    db: Session,
    migration: Migration,
    record: EmployeeRecord,
    *,
    max_attempts: int | None = None,
) -> bool:
    """Push one record, retrying transient failures. Returns True on success."""
    max_attempts = max_attempts or settings.max_push_attempts
    payload = build_payload(record)
    attempts_this_call = 0

    while attempts_this_call < max_attempts:
        attempts_this_call += 1
        record.push_attempt_count += 1
        attempt_no = record.push_attempt_count

        response = target_api.create_employee(
            db, payload, migration_ref=migration.migration_id, attempt=attempt_no
        )

        db.add(
            PushAttempt(
                migration_id=migration.id,
                migration_ref=migration.migration_id,
                employee_record_id=record.id,
                employee_id=record.employee_id or "",
                attempt=attempt_no,
                status=response.status,
                failure_kind=response.failure_kind,
                error=response.error,
                payload=payload,
                target_response=response.as_dict(),
                idempotency_key=_idempotency_key(migration, record),
            )
        )

        bus.publish(
            migration.migration_id,
            "push",
            {
                "employee_id": record.employee_id,
                "attempt": attempt_no,
                "status": response.status,
                "error": response.error,
                "failure_kind": response.failure_kind,
            },
        )

        if response.status == "success":
            record.status = str(RecordStatus.PUSHED)
            record.push_status = "success"
            record.push_error = None
            record.push_failure_kind = None
            audit.record(
                db,
                migration,
                AuditEventType.RECORD_PUSHED,
                summary=(
                    f"{record.employee_id} accepted by the target platform "
                    f"(attempt {attempt_no})"
                ),
                actor=Actor.TARGET_API,
                record_ref=record.employee_id,
                after=payload,
                details={
                    "attempt": attempt_no,
                    "idempotent": response.idempotent,
                    "status_code": response.status_code,
                },
            )
            return True

        record.push_status = "failed"
        record.push_error = response.error
        record.push_failure_kind = response.failure_kind
        audit.record(
            db,
            migration,
            AuditEventType.API_FAILURE,
            summary=f"{record.employee_id} rejected by the target (attempt {attempt_no})",
            reason=response.error,
            actor=Actor.TARGET_API,
            record_ref=record.employee_id,
            details={
                "attempt": attempt_no,
                "failure_kind": response.failure_kind,
                "status_code": response.status_code,
            },
        )

        if response.failure_kind != str(FailureKind.TRANSIENT):
            record.status = str(RecordStatus.FAILED)
            return False

        if attempts_this_call < max_attempts:
            delay = settings.retry_base_delay_seconds * (2 ** (attempts_this_call - 1))
            audit.record(
                db,
                migration,
                AuditEventType.RETRY,
                summary=(
                    f"Retrying {record.employee_id} in {delay:.1f}s "
                    f"(attempt {attempts_this_call + 1} of {max_attempts})"
                ),
                reason="Transient target error - retried automatically without human input",
                actor=Actor.AGENT,
                record_ref=record.employee_id,
                details={"backoff_seconds": round(delay, 2), "next_attempt": attempt_no + 1},
            )
            db.commit()
            await asyncio.sleep(delay)

    record.status = str(RecordStatus.FAILED)
    return False
