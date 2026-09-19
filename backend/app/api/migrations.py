"""Migration lifecycle + read models for the dashboard."""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import DATA_DIR, get_target_schema, settings
from ..database import get_db
from ..models import (
    AUDIT_CATEGORIES,
    AuditEvent,
    EmployeeRecord,
    Escalation,
    EscalationStatus,
    FieldMapping,
    Migration,
    MigrationState,
    PushAttempt,
    RecordStatus,
)
from ..schemas import (
    AuditEventOut,
    CreateMigrationRequest,
    EscalationOut,
    FieldMappingOut,
    MigrationDetail,
    MigrationSummary,
    PushAttemptOut,
    RecordOut,
)
from ..services import migration_agent, rollback
from ..services.events import bus
from ..utils.errors import InvalidStateError, ValidationError
from ..utils.logging import get_logger

router = APIRouter(prefix="/api/migrations", tags=["migrations"])
log = get_logger("api")

UPLOAD_DIR = DATA_DIR / "uploads"


def _elapsed(migration: Migration) -> float | None:
    if not migration.started_at:
        return None
    start = migration.started_at.replace(tzinfo=timezone.utc)
    end = (
        migration.completed_at.replace(tzinfo=timezone.utc)
        if migration.completed_at
        else datetime.now(timezone.utc)
    )
    return round((end - start).total_seconds(), 1)


def _detail(db: Session, migration: Migration) -> MigrationDetail:
    open_escalations = (
        db.query(Escalation)
        .filter(
            Escalation.migration_id == migration.id,
            Escalation.status == str(EscalationStatus.OPEN),
        )
        .count()
    )
    pushed = (
        db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.migration_id == migration.id,
            EmployeeRecord.status == str(RecordStatus.PUSHED),
        )
        .count()
    )
    retryable = [
        r
        for r in db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.migration_id == migration.id,
            EmployeeRecord.status == str(RecordStatus.FAILED),
        )
        .all()
        if r.push_failure_kind != "permanent"
    ]
    ready = (
        db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.migration_id == migration.id,
            EmployeeRecord.status == str(RecordStatus.READY),
        )
        .count()
    )

    state = migration.state
    running = migration_agent.is_running(migration.migration_id)
    detail = MigrationDetail.model_validate(migration)
    detail.files = [f for f in migration.files]  # type: ignore[assignment]
    detail.elapsed_seconds = _elapsed(migration)
    detail.open_escalations = open_escalations
    detail.can_start = state == str(MigrationState.CREATED) and not running
    detail.can_pause = running and state not in (
        str(MigrationState.WAITING_FOR_HUMAN),
        str(MigrationState.COMPLETED),
    )
    detail.can_resume = state == str(MigrationState.PAUSED) and not running
    detail.can_push = (
        state in (str(MigrationState.READY_TO_PUSH), str(MigrationState.COMPLETED))
        and ready > 0
        and not running
    )
    detail.can_retry = bool(retryable) and not running
    detail.can_rollback = pushed > 0 and not running
    return detail


@router.get("", response_model=list[MigrationSummary])
def list_migrations(db: Session = Depends(get_db)) -> list[MigrationSummary]:
    rows = db.query(Migration).order_by(Migration.id.desc()).limit(50).all()
    return [MigrationSummary.model_validate(m) for m in rows]


@router.post("", response_model=MigrationDetail, status_code=201)
def create_migration(
    payload: CreateMigrationRequest, db: Session = Depends(get_db)
) -> MigrationDetail:
    if not payload.use_demo_data:
        raise ValidationError(
            "Uploading files? Use POST /api/migrations/upload instead.",
        )
    migration = migration_agent.create_migration(
        db, name=payload.name, file_paths=migration_agent.demo_file_paths(), mode="demo"
    )
    db.commit()
    db.refresh(migration)
    if payload.auto_start:
        migration_agent.start(migration.migration_id)
    return _detail(db, migration)


@router.post("/upload", response_model=MigrationDetail, status_code=201)
async def create_migration_from_upload(
    files: list[UploadFile] = File(...),
    name: str = Query(default="Employee migration"),
    auto_start: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> MigrationDetail:
    if not files:
        raise ValidationError("At least one CSV or XLSX file is required")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    saved: list[Path] = []
    for upload in files:
        original = Path(upload.filename or "upload.csv").name  # strip any path
        if Path(original).suffix.lower() not in settings.allowed_extensions:
            raise ValidationError(
                f"'{original}' is not an allowed file type "
                f"({sorted(settings.allowed_extensions)})"
            )
        destination = UPLOAD_DIR / f"{stamp}_{original}"
        with destination.open("wb") as fh:
            shutil.copyfileobj(upload.file, fh, length=1024 * 1024)
        if destination.stat().st_size > settings.upload_max_bytes:
            destination.unlink(missing_ok=True)
            raise ValidationError(
                f"'{original}' exceeds the {settings.upload_max_bytes} byte limit"
            )
        saved.append(destination)

    migration = migration_agent.create_migration(
        db, name=name, file_paths=saved, mode="upload"
    )
    db.commit()
    db.refresh(migration)
    if auto_start:
        migration_agent.start(migration.migration_id)
    return _detail(db, migration)


@router.get("/{migration_ref}", response_model=MigrationDetail)
def get_migration(migration_ref: str, db: Session = Depends(get_db)) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    return _detail(db, migration)


@router.post("/{migration_ref}/start", response_model=MigrationDetail)
def start_migration(migration_ref: str, db: Session = Depends(get_db)) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    if migration.state != str(MigrationState.CREATED):
        raise InvalidStateError(
            f"Migration is {migration.state}; only a CREATED migration can be started"
        )
    migration_agent.start(migration_ref)
    return _detail(db, migration)


@router.post("/{migration_ref}/pause", response_model=MigrationDetail)
def pause_migration(migration_ref: str, db: Session = Depends(get_db)) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    if not migration_agent.is_running(migration_ref):
        raise InvalidStateError("The agent is not currently running")
    migration.pause_requested = True
    db.commit()
    return _detail(db, migration)


@router.post("/{migration_ref}/resume", response_model=MigrationDetail)
def resume_migration(migration_ref: str, db: Session = Depends(get_db)) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    if migration.state not in (
        str(MigrationState.PAUSED),
        str(MigrationState.WAITING_FOR_HUMAN),
    ):
        raise InvalidStateError(f"Migration is {migration.state}; nothing to resume")
    migration.pause_requested = False
    db.commit()
    migration_agent.resume(migration_ref)
    return _detail(db, migration)


@router.post("/{migration_ref}/push", response_model=MigrationDetail)
def push_migration(migration_ref: str, db: Session = Depends(get_db)) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    if migration.state not in (
        str(MigrationState.READY_TO_PUSH),
        str(MigrationState.COMPLETED),
    ):
        raise InvalidStateError(
            f"Migration is {migration.state}; it must be READY_TO_PUSH before a push"
        )
    migration_agent.schedule_push(migration_ref)
    return _detail(db, migration)


@router.post("/{migration_ref}/retry", response_model=MigrationDetail)
def retry_failed(migration_ref: str, db: Session = Depends(get_db)) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    migration_agent.schedule_push(migration_ref, only_failed=True)
    return _detail(db, migration)


@router.post("/{migration_ref}/rollback", response_model=MigrationDetail)
def rollback_migration(
    migration_ref: str,
    actor: str = Query(default="implementation_consultant"),
    db: Session = Depends(get_db),
) -> MigrationDetail:
    migration = migration_agent.get_migration(db, migration_ref)
    if migration_agent.is_running(migration_ref):
        raise InvalidStateError("Cannot roll back while the agent is running")
    rollback.rollback_migration(db, migration, actor_name=actor)
    db.commit()
    return _detail(db, migration)


# ---------------------------------------------------------------------------
# read models
# ---------------------------------------------------------------------------
@router.get("/{migration_ref}/mappings", response_model=list[FieldMappingOut])
def list_mappings(migration_ref: str, db: Session = Depends(get_db)):
    migration = migration_agent.get_migration(db, migration_ref)
    rows = (
        db.query(FieldMapping)
        .filter(FieldMapping.migration_id == migration.id)
        .order_by(FieldMapping.source_file_name, FieldMapping.id)
        .all()
    )
    return [FieldMappingOut.model_validate(r) for r in rows]


@router.get("/{migration_ref}/records", response_model=list[RecordOut])
def list_records(
    migration_ref: str,
    filter: str = Query(
        default="all",
        pattern="^(all|cleaned|duplicates|escalated|invalid|ready|pushed|failed)$",
    ),
    limit: int = Query(default=500, le=2000),
    db: Session = Depends(get_db),
):
    migration = migration_agent.get_migration(db, migration_ref)
    query = db.query(EmployeeRecord).filter(EmployeeRecord.migration_id == migration.id)

    if filter == "cleaned":
        rows = [r for r in query.all() if r.changes]
    elif filter == "duplicates":
        rows = [r for r in query.all() if r.is_duplicate or r.merged_from]
    elif filter == "escalated":
        rows = query.filter(EmployeeRecord.status == str(RecordStatus.BLOCKED)).all()
    elif filter == "invalid":
        rows = query.filter(EmployeeRecord.status == str(RecordStatus.INVALID)).all()
    elif filter == "ready":
        rows = query.filter(EmployeeRecord.status == str(RecordStatus.READY)).all()
    elif filter == "pushed":
        rows = query.filter(EmployeeRecord.status == str(RecordStatus.PUSHED)).all()
    elif filter == "failed":
        rows = query.filter(EmployeeRecord.status == str(RecordStatus.FAILED)).all()
    else:
        rows = query.all()

    rows = sorted(rows, key=lambda r: r.id)[:limit]
    return [RecordOut.model_validate(r) for r in rows]


@router.get("/{migration_ref}/escalations", response_model=list[EscalationOut])
def list_escalations(
    migration_ref: str,
    status: str = Query(default="all"),
    db: Session = Depends(get_db),
):
    migration = migration_agent.get_migration(db, migration_ref)
    query = db.query(Escalation).filter(Escalation.migration_id == migration.id)
    if status.lower() != "all":
        query = query.filter(Escalation.status == status.upper())
    rows = query.order_by(Escalation.status != "OPEN", Escalation.id).all()
    return [EscalationOut.model_validate(r) for r in rows]


@router.get("/{migration_ref}/audit", response_model=list[AuditEventOut])
def list_audit(
    migration_ref: str,
    actor: str | None = Query(default=None),
    category: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=500, le=5000),
    db: Session = Depends(get_db),
):
    migration = migration_agent.get_migration(db, migration_ref)
    query = db.query(AuditEvent).filter(AuditEvent.migration_id == migration.id)
    if actor:
        query = query.filter(AuditEvent.actor == actor)
    if category and category in AUDIT_CATEGORIES:
        query = query.filter(AuditEvent.event.in_([str(e) for e in AUDIT_CATEGORIES[category]]))
    if q:
        like = f"%{q}%"
        query = query.filter(AuditEvent.summary.ilike(like) | AuditEvent.reason.ilike(like))
    rows = query.order_by(AuditEvent.id.desc()).limit(limit).all()
    return [AuditEventOut.model_validate(r) for r in rows]


@router.get("/{migration_ref}/push-attempts", response_model=list[PushAttemptOut])
def list_push_attempts(migration_ref: str, db: Session = Depends(get_db)):
    migration = migration_agent.get_migration(db, migration_ref)
    rows = (
        db.query(PushAttempt)
        .filter(PushAttempt.migration_id == migration.id)
        .order_by(PushAttempt.id)
        .all()
    )
    return [PushAttemptOut.model_validate(r) for r in rows]


@router.get("/{migration_ref}/activity")
async def activity_stream(migration_ref: str, db: Session = Depends(get_db)):
    """Server-Sent Events stream of live agent activity."""
    migration_agent.get_migration(db, migration_ref)  # 404 early if unknown
    queue = bus.subscribe(migration_ref)

    async def generator():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield bus.to_sse(event)
        except asyncio.CancelledError:  # pragma: no cover - client disconnect
            raise
        finally:
            bus.unsubscribe(migration_ref, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{migration_ref}/schema")
def migration_schema(migration_ref: str, db: Session = Depends(get_db)):
    migration = migration_agent.get_migration(db, migration_ref)
    return {
        "target_schema": get_target_schema(),
        "source_files": [
            {
                "filename": f.filename,
                "columns": list((f.inferred_schema or {}).keys()),
                "profile": f.inferred_schema,
            }
            for f in migration.files
        ],
    }
