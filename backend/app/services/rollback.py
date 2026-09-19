"""Rollback: remove everything this migration wrote to the target platform.

Reversibility is half of the autonomy argument in this project, so it has to
actually work. Every successful push is tagged with the migration id, and
rollback deletes exactly that set - nothing that was already in the target
before the migration ran.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (
    Actor,
    AuditEventType,
    EmployeeRecord,
    Migration,
    MigrationState,
    RecordStatus,
)
from ..utils.errors import InvalidStateError
from . import audit, target_api
from .events import bus


def rollback_migration(db: Session, migration: Migration, *, actor_name: str = "system") -> dict:
    pushed = (
        db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.migration_id == migration.id,
            EmployeeRecord.status == str(RecordStatus.PUSHED),
        )
        .all()
    )
    if not pushed:
        raise InvalidStateError(
            "Nothing to roll back - this migration has no successfully pushed records",
            details={"migration_id": migration.migration_id},
        )

    audit.record(
        db,
        migration,
        AuditEventType.ROLLBACK,
        summary=f"Rollback started for {len(pushed)} record(s)",
        reason="Destructive operation explicitly requested by a human",
        actor=Actor.HUMAN,
        actor_name=actor_name,
        details={"record_count": len(pushed)},
    )

    removed, failed = 0, 0
    for record in pushed:
        response = target_api.delete_employee(
            db, record.employee_id or "", migration_ref=migration.migration_id
        )
        if response.status == "success":
            record.status = str(RecordStatus.ROLLED_BACK)
            record.push_status = "rolled_back"
            removed += 1
        else:
            failed += 1
        audit.record(
            db,
            migration,
            AuditEventType.ROLLBACK,
            summary=(
                f"{record.employee_id} removed from the target platform"
                if response.status == "success"
                else f"Could not remove {record.employee_id}"
            ),
            reason=response.error,
            actor=Actor.TARGET_API,
            record_ref=record.employee_id,
            before=record.transformed,
            after=None,
            details={"status_code": response.status_code},
        )
        bus.publish(
            migration.migration_id,
            "rollback",
            {"employee_id": record.employee_id, "status": response.status},
        )

    migration.state = str(MigrationState.ROLLED_BACK)
    migration.current_step = f"Rolled back {removed} record(s) from the target platform"
    stats = dict(migration.stats or {})
    stats.update({"rolled_back": removed, "rollback_failures": failed, "pushed": 0})
    migration.stats = stats
    db.flush()

    audit.record(
        db,
        migration,
        AuditEventType.ROLLBACK,
        summary=f"Rollback complete - {removed} removed, {failed} failed",
        actor=Actor.AGENT,
        details={"removed": removed, "failed": failed},
    )
    bus.publish(
        migration.migration_id,
        "state",
        {"state": migration.state, "current_step": migration.current_step, "stats": stats},
    )
    return {"removed": removed, "failed": failed}
