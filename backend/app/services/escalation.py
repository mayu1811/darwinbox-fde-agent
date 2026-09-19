"""Escalation creation and resolution - the human-in-the-loop boundary.

The agent escalates ONLY for the six reasons enumerated in EscalationType.
Everything else it handles itself. See docs/approach.md for the argument.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import (
    Actor,
    AuditEventType,
    Escalation,
    EscalationStatus,
    EscalationType,
    Migration,
    Severity,
    utcnow,
)
from ..utils.errors import ConflictError, NotFoundError, ValidationError
from . import audit
from .events import bus

#: Severity drives ordering in the review queue, not whether we block.
DEFAULT_SEVERITY = {
    EscalationType.AMBIGUOUS_MAPPING: Severity.HIGH,
    EscalationType.MISSING_MANDATORY_FIELD: Severity.HIGH,
    EscalationType.DUPLICATE_CONFLICT: Severity.MEDIUM,
    EscalationType.VALIDATION_FAILURE: Severity.MEDIUM,
    EscalationType.UNSAFE_VALUE: Severity.LOW,
    EscalationType.DESTRUCTIVE_ACTION: Severity.HIGH,
}


def create(
    db: Session,
    migration: Migration,
    *,
    type_: EscalationType,
    title: str,
    reason: str,
    confidence: float = 0.0,
    severity: Severity | None = None,
    source_file: str | None = None,
    source_field: str | None = None,
    source_value: str | None = None,
    candidate_values: list[dict] | None = None,
    sample_values: list[str] | None = None,
    record_id: str | None = None,
    affected_record_ids: list[int] | None = None,
    field_mapping_id: int | None = None,
    agent_recommendation: str | None = None,
    blocking: bool = True,
) -> Escalation:
    escalation = Escalation(
        migration_id=migration.id,
        type=str(type_),
        severity=str(severity or DEFAULT_SEVERITY.get(type_, Severity.MEDIUM)),
        title=title,
        source_file=source_file,
        source_field=source_field,
        source_value=source_value,
        candidate_values=candidate_values or [],
        sample_values=sample_values or [],
        record_id=record_id,
        affected_record_ids=affected_record_ids or [],
        field_mapping_id=field_mapping_id,
        reason=reason,
        agent_recommendation=agent_recommendation,
        confidence=confidence,
        blocking=blocking,
        status=str(EscalationStatus.OPEN),
    )
    db.add(escalation)
    db.flush()

    audit.record(
        db,
        migration,
        AuditEventType.ESCALATION_CREATED,
        summary=title,
        reason=reason,
        actor=Actor.AGENT,
        record_ref=record_id,
        confidence=confidence,
        details={
            "escalation_id": escalation.id,
            "type": str(type_),
            "severity": escalation.severity,
            "candidates": escalation.candidate_values,
        },
    )
    bus.publish(
        migration.migration_id,
        "escalation",
        {"action": "created", "escalation_id": escalation.id, "type": str(type_), "title": title},
    )
    return escalation


def open_escalations(db: Session, migration: Migration) -> list[Escalation]:
    return (
        db.query(Escalation)
        .filter(
            Escalation.migration_id == migration.id,
            Escalation.status == str(EscalationStatus.OPEN),
        )
        .order_by(Escalation.id)
        .all()
    )


def has_blocking_escalations(db: Session, migration: Migration) -> bool:
    return any(e.blocking for e in open_escalations(db, migration))


def get(db: Session, escalation_id: int) -> Escalation:
    escalation = db.get(Escalation, escalation_id)
    if not escalation:
        raise NotFoundError(f"Escalation {escalation_id} not found")
    return escalation


def resolve(
    db: Session,
    escalation: Escalation,
    *,
    decision: EscalationStatus,
    chosen_value: str | None = None,
    note: str | None = None,
    resolved_by: str = "implementation_consultant",
) -> Escalation:
    """Apply a human decision. Does not itself re-run the pipeline."""
    if escalation.status != str(EscalationStatus.OPEN):
        raise ConflictError(
            f"Escalation {escalation.id} is already {escalation.status}",
            details={"status": escalation.status},
        )

    if decision in (EscalationStatus.APPROVED, EscalationStatus.CORRECTED):
        if chosen_value is None:
            if decision == EscalationStatus.APPROVED and escalation.candidate_values:
                chosen_value = escalation.candidate_values[0].get("value")
            if chosen_value is None:
                raise ValidationError(
                    "A value is required to approve or correct this escalation",
                    details={"escalation_id": escalation.id},
                )

    escalation.status = str(decision)
    escalation.resolution = {
        "decision": str(decision),
        "value": chosen_value,
        "note": note,
    }
    escalation.resolved_by = resolved_by
    escalation.resolved_at = utcnow()
    db.flush()

    migration = escalation.migration
    audit.record(
        db,
        migration,
        AuditEventType.HUMAN_DECISION,
        summary=f"{decision} - {escalation.title}",
        reason=note or f"Resolved by {resolved_by}",
        actor=Actor.HUMAN,
        actor_name=resolved_by,
        record_ref=escalation.record_id,
        before={"status": str(EscalationStatus.OPEN)},
        after={"status": str(decision), "value": chosen_value},
        details={
            "escalation_id": escalation.id,
            "type": escalation.type,
            "chosen_value": chosen_value,
        },
    )
    bus.publish(
        migration.migration_id,
        "escalation",
        {
            "action": "resolved",
            "escalation_id": escalation.id,
            "decision": str(decision),
            "value": chosen_value,
        },
    )
    return escalation
