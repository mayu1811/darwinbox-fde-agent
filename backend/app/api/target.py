"""Mock target platform HTTP surface.

Mounted in the same process for demo convenience, but it is a real service
boundary: the agent only ever talks to it through services/target_api.py.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import TargetEmployeeOut
from ..services import target_api

router = APIRouter(prefix="/target", tags=["mock target platform"])


@router.post("/employees")
def create_employee(
    payload: dict = Body(...),
    migration_id: str | None = Query(default=None),
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    result = target_api.create_employee(db, payload, migration_ref=migration_id)
    db.commit()
    if response is not None:
        response.status_code = result.status_code
    return result.as_dict()


@router.post("/employees/bulk")
def bulk_create(
    payloads: list[dict] = Body(...),
    migration_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    results = target_api.bulk_create(db, payloads, migration_ref=migration_id)
    db.commit()
    return {
        "total": len(results),
        "succeeded": sum(1 for r in results if r.status == "success"),
        "failed": sum(1 for r in results if r.status != "success"),
        "results": [r.as_dict() for r in results],
    }


@router.get("/employees", response_model=list[TargetEmployeeOut])
def list_employees(
    migration_id: str | None = Query(default=None),
    limit: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
):
    rows = target_api.list_employees(db, migration_ref=migration_id, limit=limit)
    return [TargetEmployeeOut.model_validate(r) for r in rows]


@router.delete("/employees/{employee_id}")
def delete_employee(
    employee_id: str,
    migration_id: str | None = Query(default=None),
    response: Response = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    result = target_api.delete_employee(db, employee_id, migration_ref=migration_id)
    db.commit()
    if response is not None:
        response.status_code = 200 if result.status == "success" else result.status_code
    return result.as_dict()


@router.get("/meta")
def target_meta():
    """What the target platform will and will not accept - shown in the UI."""
    from ..config import settings

    return {
        "department_master_data": sorted(target_api.DEPARTMENT_MASTER),
        "required_fields": list(target_api.REQUIRED_TARGET_FIELDS),
        "simulated_transient_failures": settings.transient_failure_profile,
    }
