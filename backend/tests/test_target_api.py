"""Mock target platform, retry and rollback behaviour."""
from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.models import (
    EmployeeRecord,
    Migration,
    MigrationState,
    PushAttempt,
    RecordStatus,
    TargetEmployee,
)
from app.services import retry as retry_service
from app.services import rollback, target_api
from app.utils.errors import InvalidStateError

VALID = {
    "employee_id": "EMP9001",
    "full_name": "Test Person",
    "email": "test.person@acme-corp.com",
    "department": "Engineering",
    "status": "active",
}


def _migration(db) -> Migration:
    migration = Migration(
        migration_id="MIG-TEST-001",
        name="test",
        state=str(MigrationState.READY_TO_PUSH),
        stats={},
    )
    db.add(migration)
    db.flush()
    return migration


def _record(db, migration: Migration, payload: dict) -> EmployeeRecord:
    record = EmployeeRecord(
        migration_id=migration.id,
        source_file_name="test.csv",
        source_row_number=2,
        employee_id=payload["employee_id"],
        transformed=payload,
        status=str(RecordStatus.READY),
    )
    db.add(record)
    db.flush()
    return record


# ------------------------------------------------------------- target API
def test_successful_push_creates_a_target_record(db):
    response = target_api.create_employee(db, VALID, migration_ref="MIG-TEST-001")
    assert response.status == "success"
    assert response.status_code == 201
    assert db.query(TargetEmployee).count() == 1


def test_push_is_idempotent_on_employee_id(db):
    target_api.create_employee(db, VALID, migration_ref="MIG-TEST-001")
    second = target_api.create_employee(db, VALID, migration_ref="MIG-TEST-001")
    assert second.status == "success"
    assert second.idempotent is True
    assert db.query(TargetEmployee).count() == 1, "a retry must not duplicate the record"


def test_target_rejects_unknown_department_permanently(db):
    response = target_api.create_employee(
        db, {**VALID, "department": "Ops Excellence"}, migration_ref="MIG-TEST-001"
    )
    assert response.status == "failed"
    assert response.failure_kind == "permanent"
    assert response.status_code == 422


def test_target_rejects_missing_mandatory_field(db):
    response = target_api.create_employee(db, {**VALID, "email": None})
    assert response.status == "failed"
    assert response.failure_kind == "permanent"


def test_transient_failure_is_deterministic(db):
    emp_id, fails_until = next(iter(settings.transient_failure_profile.items()))
    payload = {**VALID, "employee_id": emp_id}
    for attempt in range(1, fails_until + 1):
        response = target_api.create_employee(db, payload, attempt=attempt)
        assert response.failure_kind == "transient", f"attempt {attempt} should fail"
    ok = target_api.create_employee(db, payload, attempt=fails_until + 1)
    assert ok.status == "success"


def test_bulk_push_returns_per_record_status(db):
    responses = target_api.bulk_create(
        db,
        [VALID, {**VALID, "employee_id": "EMP9002", "department": "Nowhere"}],
        migration_ref="MIG-TEST-001",
    )
    assert [r.status for r in responses] == ["success", "failed"]


def test_delete_removes_from_target(db):
    target_api.create_employee(db, VALID, migration_ref="MIG-TEST-001")
    response = target_api.delete_employee(db, VALID["employee_id"])
    assert response.status == "success"
    assert db.query(TargetEmployee).count() == 0


# ------------------------------------------------------------------ retry
def test_transient_failures_are_retried_until_success(db):
    migration = _migration(db)
    emp_id = next(
        k for k, v in settings.transient_failure_profile.items()
        if v < settings.max_push_attempts
    )
    record = _record(db, migration, {**VALID, "employee_id": emp_id})

    ok = asyncio.run(retry_service.push_record(db, migration, record))

    assert ok is True
    assert record.status == str(RecordStatus.PUSHED)
    attempts = db.query(PushAttempt).filter(PushAttempt.employee_id == emp_id).all()
    assert len(attempts) > 1, "expected at least one retry"
    assert attempts[-1].status == "success"
    assert all(a.failure_kind == "transient" for a in attempts[:-1])


def test_permanent_failure_is_not_retried(db):
    migration = _migration(db)
    record = _record(db, migration, {**VALID, "department": "Ops Excellence"})

    ok = asyncio.run(retry_service.push_record(db, migration, record))

    assert ok is False
    assert record.status == str(RecordStatus.FAILED)
    assert record.push_failure_kind == "permanent"
    assert db.query(PushAttempt).count() == 1, "a 422 must not be retried"


def test_retry_gives_up_after_max_attempts(db):
    migration = _migration(db)
    emp_id = next(
        (k for k, v in settings.transient_failure_profile.items()
         if v >= settings.max_push_attempts),
        None,
    )
    if emp_id is None:
        pytest.skip("no always-failing id configured")
    record = _record(db, migration, {**VALID, "employee_id": emp_id})

    ok = asyncio.run(retry_service.push_record(db, migration, record))

    assert ok is False
    assert record.status == str(RecordStatus.FAILED)
    assert record.push_attempt_count == settings.max_push_attempts


# --------------------------------------------------------------- rollback
def test_rollback_removes_only_this_migrations_records(db):
    migration = _migration(db)
    record = _record(db, migration, VALID)
    asyncio.run(retry_service.push_record(db, migration, record))

    # A record that was already in the target before this migration ran.
    db.add(TargetEmployee(employee_id="PRE-EXISTING", migration_ref=None, payload={}))
    db.flush()

    result = rollback.rollback_migration(db, migration, actor_name="tester")

    assert result == {"removed": 1, "failed": 0}
    assert record.status == str(RecordStatus.ROLLED_BACK)
    remaining = {r.employee_id for r in db.query(TargetEmployee).all()}
    assert remaining == {"PRE-EXISTING"}
    assert migration.state == str(MigrationState.ROLLED_BACK)


def test_rollback_refuses_when_nothing_was_pushed(db):
    migration = _migration(db)
    with pytest.raises(InvalidStateError):
        rollback.rollback_migration(db, migration)
