"""Mock target platform.

This stands in for the customer's new HR platform. It is deliberately
*unreliable in a realistic way*:

  * a couple of employees hit transient 503s before succeeding (retry demo)
  * the target rejects departments that are not in its master list (a
    permanent 422 - retrying will never help)
  * writes are idempotent on employee_id, so a retry after an ambiguous
    failure cannot create a duplicate

Failures are keyed off deterministic rules rather than random(), so the
reviewer sees the same story every run.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import settings
from ..models import TargetCallLog, TargetEmployee, utcnow
from ..utils.text import is_valid_email

#: The target platform only accepts departments that exist in its master data.
DEPARTMENT_MASTER = {
    "Engineering",
    "Finance",
    "Human Resources",
    "Sales",
    "Marketing",
    "Design",
    "Operations",
    "Customer Success",
}

REQUIRED_TARGET_FIELDS = ("employee_id", "full_name", "email", "status")


@dataclass
class TargetResponse:
    employee_id: str
    status: str            # "success" | "failed"
    status_code: int
    error: str | None = None
    failure_kind: str | None = None  # "transient" | "permanent"
    idempotent: bool = False

    def as_dict(self) -> dict:
        body = {"employee_id": self.employee_id, "status": self.status}
        if self.error:
            body["error"] = self.error
            body["failure_kind"] = self.failure_kind
        if self.idempotent:
            body["idempotent"] = True
        return body


def _log(
    db: Session,
    migration_ref: str | None,
    employee_id: str | None,
    operation: str,
    attempt: int,
    response: TargetResponse | dict,
    status_code: int,
) -> None:
    payload = response.as_dict() if isinstance(response, TargetResponse) else response
    db.add(
        TargetCallLog(
            migration_ref=migration_ref,
            employee_id=employee_id,
            operation=operation,
            attempt=attempt,
            status_code=status_code,
            response=payload,
        )
    )


def _validate_payload(payload: dict) -> TargetResponse | None:
    employee_id = str(payload.get("employee_id") or "")
    for field_name in REQUIRED_TARGET_FIELDS:
        if not payload.get(field_name):
            return TargetResponse(
                employee_id=employee_id,
                status="failed",
                status_code=422,
                error=f"Target rejected the record: '{field_name}' is required",
                failure_kind="permanent",
            )
    if not is_valid_email(str(payload["email"])):
        return TargetResponse(
            employee_id=employee_id,
            status="failed",
            status_code=422,
            error="Target rejected the record: invalid email address",
            failure_kind="permanent",
        )
    if payload.get("status") not in ("active", "inactive"):
        return TargetResponse(
            employee_id=employee_id,
            status="failed",
            status_code=422,
            error="Target rejected the record: status must be active or inactive",
            failure_kind="permanent",
        )
    department = payload.get("department")
    if department and department not in DEPARTMENT_MASTER:
        return TargetResponse(
            employee_id=employee_id,
            status="failed",
            status_code=422,
            error=(
                f"Target rejected the record: department '{department}' does not exist in "
                "the target platform master data"
            ),
            failure_kind="permanent",
        )
    return None


def create_employee(
    db: Session,
    payload: dict,
    *,
    migration_ref: str | None = None,
    attempt: int = 1,
) -> TargetResponse:
    employee_id = str(payload.get("employee_id") or "")

    # 1. Simulated transient infrastructure failure (deterministic).
    fails_until = settings.transient_failure_profile.get(employee_id.upper(), 0)
    if attempt <= fails_until:
        response = TargetResponse(
            employee_id=employee_id,
            status="failed",
            status_code=503,
            error="Temporary target API error (503) - upstream service unavailable",
            failure_kind="transient",
        )
        _log(db, migration_ref, employee_id, "create", attempt, response, 503)
        return response

    # 2. Target-side validation.
    rejection = _validate_payload(payload)
    if rejection:
        _log(db, migration_ref, employee_id, "create", attempt, rejection, rejection.status_code)
        return rejection

    # 3. Idempotent upsert on the primary key.
    existing = (
        db.query(TargetEmployee).filter(TargetEmployee.employee_id == employee_id).one_or_none()
    )
    if existing:
        existing.payload = payload
        existing.migration_ref = migration_ref
        existing.updated_at = utcnow()
        response = TargetResponse(
            employee_id=employee_id, status="success", status_code=200, idempotent=True
        )
    else:
        db.add(
            TargetEmployee(
                employee_id=employee_id, migration_ref=migration_ref, payload=payload
            )
        )
        response = TargetResponse(employee_id=employee_id, status="success", status_code=201)

    db.flush()
    _log(db, migration_ref, employee_id, "create", attempt, response, response.status_code)
    return response


def bulk_create(
    db: Session, payloads: list[dict], *, migration_ref: str | None = None
) -> list[TargetResponse]:
    return [create_employee(db, p, migration_ref=migration_ref) for p in payloads]


def list_employees(
    db: Session, migration_ref: str | None = None, limit: int = 500
) -> list[TargetEmployee]:
    query = db.query(TargetEmployee)
    if migration_ref:
        query = query.filter(TargetEmployee.migration_ref == migration_ref)
    return query.order_by(TargetEmployee.employee_id).limit(limit).all()


def delete_employee(
    db: Session, employee_id: str, *, migration_ref: str | None = None
) -> TargetResponse:
    row = (
        db.query(TargetEmployee).filter(TargetEmployee.employee_id == employee_id).one_or_none()
    )
    if not row:
        response = TargetResponse(
            employee_id=employee_id,
            status="failed",
            status_code=404,
            error="Employee not found in the target platform",
            failure_kind="permanent",
        )
        _log(db, migration_ref, employee_id, "delete", 1, response, 404)
        return response
    db.delete(row)
    db.flush()
    response = TargetResponse(employee_id=employee_id, status="success", status_code=204)
    _log(db, migration_ref, employee_id, "delete", 1, response, 204)
    return response


def count_employees(db: Session, migration_ref: str | None = None) -> int:
    query = db.query(TargetEmployee)
    if migration_ref:
        query = query.filter(TargetEmployee.migration_ref == migration_ref)
    return query.count()
