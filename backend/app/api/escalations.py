"""Human-in-the-loop endpoints.

Resolving the last open escalation automatically resumes the agent - the
consultant makes a decision, not a sequence of clicks.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EscalationStatus, MigrationState
from ..schemas import EscalationOut, EscalationResolveRequest
from ..services import escalation as escalation_service
from ..services import migration_agent
from ..utils.errors import ValidationError
from ..utils.logging import get_logger

router = APIRouter(prefix="/api/escalations", tags=["escalations"])
log = get_logger("api")


def _maybe_resume(db: Session, migration) -> bool:
    """Resume the agent once nothing blocking is left."""
    if escalation_service.has_blocking_escalations(db, migration):
        return False
    if migration.state not in (
        str(MigrationState.WAITING_FOR_HUMAN),
        str(MigrationState.PAUSED),
    ):
        return False
    if migration_agent.is_running(migration.migration_id):
        return False
    migration_agent.resume(migration.migration_id)
    return True


@router.get("/{escalation_id}", response_model=EscalationOut)
def get_escalation(escalation_id: int, db: Session = Depends(get_db)) -> EscalationOut:
    return EscalationOut.model_validate(escalation_service.get(db, escalation_id))


@router.post("/{escalation_id}/resolve")
def resolve_escalation(
    escalation_id: int,
    payload: EscalationResolveRequest,
    db: Session = Depends(get_db),
):
    escalation = escalation_service.get(db, escalation_id)
    decision = EscalationStatus(payload.decision)

    if decision is EscalationStatus.REJECTED:
        return reject_escalation(escalation_id, payload, db)

    value = payload.value
    if decision is EscalationStatus.APPROVED and value is None:
        if not escalation.candidate_values:
            raise ValidationError(
                "This escalation has no agent proposal to approve - provide a value"
            )
        value = escalation.candidate_values[0].get("value")

    escalation_service.resolve(
        db,
        escalation,
        decision=decision,
        chosen_value=value,
        note=payload.note,
        resolved_by=payload.resolved_by,
    )
    migration = escalation.migration
    db.commit()

    resumed = _maybe_resume(db, migration)
    log.info(
        "escalation_resolved",
        escalation_id=escalation_id,
        decision=str(decision),
        resumed=resumed,
    )
    return {
        "escalation": EscalationOut.model_validate(escalation),
        "agent_resumed": resumed,
        "open_escalations": len(escalation_service.open_escalations(db, migration)),
    }


@router.post("/{escalation_id}/reject")
def reject_escalation(
    escalation_id: int,
    payload: EscalationResolveRequest | None = None,
    db: Session = Depends(get_db),
):
    escalation = escalation_service.get(db, escalation_id)
    note = payload.note if payload else None
    resolved_by = payload.resolved_by if payload else "implementation_consultant"

    escalation_service.resolve(
        db,
        escalation,
        decision=EscalationStatus.REJECTED,
        chosen_value=None,
        note=note or "Rejected - the affected data will not be migrated",
        resolved_by=resolved_by,
    )
    migration = escalation.migration
    db.commit()

    resumed = _maybe_resume(db, migration)
    return {
        "escalation": EscalationOut.model_validate(escalation),
        "agent_resumed": resumed,
        "open_escalations": len(escalation_service.open_escalations(db, migration)),
    }
