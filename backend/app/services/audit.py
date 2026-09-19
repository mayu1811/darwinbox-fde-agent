"""Audit trail.

Every meaningful decision - by the agent or by a human - lands here, with the
before/after values and the reason. This is the artefact an implementation
consultant shows the client when they ask "what did you change in my data?".
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Actor, AuditEvent, AuditEventType, Migration
from ..utils.logging import get_logger
from .events import bus

log = get_logger("audit")


def record(
    db: Session,
    migration: Migration,
    event: AuditEventType | str,
    *,
    summary: str,
    actor: Actor | str = Actor.AGENT,
    actor_name: str | None = None,
    reason: str | None = None,
    record_ref: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    details: dict | None = None,
    confidence: float | None = None,
    ai_assisted: bool = False,
    publish: bool = True,
) -> AuditEvent:
    entry = AuditEvent(
        migration_id=migration.id,
        migration_ref=migration.migration_id,
        event=str(event),
        actor=str(actor),
        actor_name=actor_name,
        summary=summary,
        reason=reason,
        record_ref=record_ref,
        before=before,
        after=after,
        details=details or {},
        confidence=confidence,
        ai_assisted=ai_assisted,
    )
    db.add(entry)
    db.flush()

    log_fields = {"migration_id": migration.migration_id, "actor": str(actor)}
    if record_ref:
        log_fields["record"] = record_ref
    if confidence is not None:
        log_fields["confidence"] = round(confidence, 3)
    level = "warn" if str(event) in {
        AuditEventType.ESCALATION_CREATED,
        AuditEventType.VALIDATION_FAILURE,
        AuditEventType.API_FAILURE,
    } else "info"
    getattr(log, level)(str(event).lower(), **log_fields)

    if publish:
        bus.publish(
            migration.migration_id,
            "audit",
            {
                "id": entry.id,
                "event": entry.event,
                "actor": entry.actor,
                "actor_name": entry.actor_name,
                "summary": entry.summary,
                "reason": entry.reason,
                "record_ref": entry.record_ref,
                "confidence": entry.confidence,
                "ai_assisted": entry.ai_assisted,
                "details": entry.details,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            },
        )
    return entry
