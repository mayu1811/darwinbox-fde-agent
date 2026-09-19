"""MigrationAgent - the orchestrator.

    INGEST -> PROFILE -> MAP -> CLEAN -> DEDUPLICATE -> VALIDATE
           -> (ESCALATE / WAIT FOR HUMAN -> REVALIDATE)
           -> PUSH -> RETRY -> (ROLLBACK)

Two properties are worth calling out in review:

1. The transform phase (MAP..VALIDATE) is **idempotent and re-runnable**. It is
   rebuilt from the immutable SourceRecord rows every time, so resuming after a
   human decision is just "run it again with one more fact known" rather than a
   fragile patch-in-place. EmployeeRecord ids are stable across re-runs, which
   is what lets an escalation keep pointing at the right record.

2. State lives in SQLite, not in the task. If the process dies mid-run the
   migration is still inspectable and resumable.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import DATA_DIR, get_target_schema, settings
from ..database import session_scope
from ..models import (
    Actor,
    AuditEventType,
    EmployeeRecord,
    Escalation,
    EscalationStatus,
    EscalationType,
    FieldMapping,
    MappingDecision,
    Migration,
    MigrationState,
    RecordStatus,
    Severity,
    SourceFile,
    SourceRecord,
    utcnow,
)
from ..utils.errors import InvalidStateError, NotFoundError
from ..utils.logging import get_logger
from ..utils.text import is_blank
from . import (
    audit,
    cleaning,
    deduplication,
    escalation as escalation_service,
    ingestion,
    mapping_agent,
    retry as retry_service,
    schema_inference,
)
from .events import bus

log = get_logger("agent")

DEMO_FILES = ["employees_legacy.csv", "employees_hr.xlsx"]

#: Higher number wins a non-critical conflict during deduplication. The HR
#: system is the more recently maintained source, so it takes precedence.
SOURCE_PRECEDENCE = {"employees_hr.xlsx": 2, "employees_legacy.csv": 1}

_running: dict[str, asyncio.Task] = {}

#: The application event loop, captured at startup.
#:
#: FastAPI runs `def` endpoints in a worker thread, where there is no running
#: loop, so `asyncio.create_task` would fail. Handing the coroutine back to the
#: main loop keeps the HTTP handlers synchronous and simple while the agent
#: still runs as a normal asyncio task.
_loop: asyncio.AbstractEventLoop | None = None


def bind_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _spawn(migration_ref: str, coro) -> None:
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        _running[migration_ref] = running.create_task(coro)
        return

    if _loop is None:  # pragma: no cover - only if used outside the app
        raise InvalidStateError(
            "No event loop is available to run the agent. "
            "Call migration_agent.bind_event_loop() during application startup."
        )

    future: asyncio.Future = asyncio.run_coroutine_threadsafe(coro, _loop)  # type: ignore[assignment]
    _running[migration_ref] = future  # type: ignore[assignment]


class PausedSignal(Exception):
    """Raised internally when a human asked the agent to stop between steps."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def get_migration(db: Session, migration_ref: str) -> Migration:
    migration = (
        db.query(Migration).filter(Migration.migration_id == migration_ref).one_or_none()
    )
    if not migration:
        raise NotFoundError(f"Migration {migration_ref} not found")
    return migration


def next_migration_ref(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.query(Migration).count() + 1
    return f"MIG-{year}-{count:03d}"


def _set_state(
    db: Session,
    migration: Migration,
    state: MigrationState,
    step: str,
    *,
    total: int | None = None,
    done: int | None = None,
) -> None:
    previous = migration.state
    migration.state = str(state)
    migration.current_step = step
    if total is not None:
        migration.progress_total = total
    if done is not None:
        migration.progress_done = done
    db.flush()
    if previous != migration.state:
        audit.record(
            db,
            migration,
            AuditEventType.MIGRATION_STATE_CHANGED,
            summary=f"{previous} -> {migration.state}",
            reason=step,
            actor=Actor.AGENT,
            publish=False,
        )
    _publish_state(migration)


def _publish_state(migration: Migration) -> None:
    bus.publish(
        migration.migration_id,
        "state",
        {
            "state": migration.state,
            "current_step": migration.current_step,
            "progress_total": migration.progress_total,
            "progress_done": migration.progress_done,
            "stats": migration.stats or {},
        },
    )


def _bump(migration: Migration, **deltas: int) -> None:
    stats = dict(migration.stats or {})
    for key, value in deltas.items():
        stats[key] = stats.get(key, 0) + value
    migration.stats = stats


def _set_stats(migration: Migration, **values) -> None:
    stats = dict(migration.stats or {})
    stats.update(values)
    migration.stats = stats


def _check_pause(db: Session, migration: Migration) -> None:
    db.refresh(migration)
    if migration.pause_requested:
        migration.pause_requested = False
        _set_state(db, migration, MigrationState.PAUSED, "Paused by the consultant")
        db.commit()
        raise PausedSignal()


async def _beat(db: Session, migration: Migration) -> None:
    db.commit()
    _check_pause(db, migration)
    await asyncio.sleep(settings.agent_step_delay_seconds)


# ---------------------------------------------------------------------------
# creation / ingestion
# ---------------------------------------------------------------------------
def create_migration(
    db: Session, *, name: str, file_paths: list[Path], mode: str = "demo"
) -> Migration:
    migration = Migration(
        migration_id=next_migration_ref(db),
        name=name,
        entity=get_target_schema()["entity"],
        state=str(MigrationState.CREATED),
        current_step="Created - waiting to start",
        mode=mode,
        llm_provider=settings.llm_provider if settings.llm_enabled else "none",
        stats={
            "files": 0,
            "source_rows": 0,
            "records": 0,
            "fields_mapped": 0,
            "fields_auto_mapped": 0,
            "fields_escalated": 0,
            "fields_ignored": 0,
            "values_cleaned": 0,
            "duplicates_found": 0,
            "duplicates_merged": 0,
            "auto_resolved": 0,
            "escalations_total": 0,
            "escalations_open": 0,
            "ready": 0,
            "invalid": 0,
            "pushed": 0,
            "failed": 0,
            "rolled_back": 0,
            "ai_assisted_decisions": 0,
        },
    )
    db.add(migration)
    db.flush()

    audit.record(
        db,
        migration,
        AuditEventType.MIGRATION_CREATED,
        summary=f"Migration {migration.migration_id} created",
        details={"mode": mode, "files": [p.name for p in file_paths]},
    )

    for path in file_paths:
        _attach_file(db, migration, path)

    db.flush()
    return migration


def _attach_file(db: Session, migration: Migration, path: Path) -> SourceFile:
    parsed = ingestion.ingest_file(path)
    source_file = SourceFile(
        migration_id=migration.id,
        filename=parsed["filename"],
        file_type=parsed["file_type"],
        size_bytes=parsed["size_bytes"],
        row_count=len(parsed["rows"]),
        column_count=len(parsed["columns"]),
        inferred_schema={},
    )
    db.add(source_file)
    db.flush()

    for row in parsed["rows"]:
        db.add(
            SourceRecord(
                migration_id=migration.id,
                source_file_id=source_file.id,
                row_number=row["row_number"],
                raw=row["raw"],
            )
        )
    db.flush()

    _bump(migration, files=1, source_rows=len(parsed["rows"]))
    audit.record(
        db,
        migration,
        AuditEventType.FILE_UPLOADED,
        summary=f"Ingested {parsed['filename']} ({len(parsed['rows'])} rows, "
        f"{len(parsed['columns'])} columns)",
        details={
            "filename": parsed["filename"],
            "rows": len(parsed["rows"]),
            "columns": parsed["columns"],
            "size_bytes": parsed["size_bytes"],
        },
    )
    return source_file


def demo_file_paths() -> list[Path]:
    paths = [DATA_DIR / name for name in DEMO_FILES]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise NotFoundError(
            f"Demo source files missing: {missing}. Run `python seed_demo.py` in backend/."
        )
    return paths


# ---------------------------------------------------------------------------
# pipeline stages
# ---------------------------------------------------------------------------
async def _stage_profile(db: Session, migration: Migration) -> None:
    _set_state(db, migration, MigrationState.PROFILING, "Profiling source columns")
    for source_file in migration.files:
        rows = [
            {"raw": r.raw}
            for r in db.query(SourceRecord)
            .filter(SourceRecord.source_file_id == source_file.id)
            .order_by(SourceRecord.row_number)
            .all()
        ]
        columns = list(rows[0]["raw"].keys()) if rows else []
        schema = schema_inference.infer_schema(columns, rows)
        source_file.inferred_schema = schema
        summary = schema_inference.summarise(schema)
        audit.record(
            db,
            migration,
            AuditEventType.SCHEMA_INFERRED,
            summary=f"Inferred schema for {source_file.filename}: "
            f"{summary['column_count']} columns",
            details={"file": source_file.filename, **summary},
        )
        await _beat(db, migration)


async def _stage_map(db: Session, migration: Migration) -> None:
    _set_state(db, migration, MigrationState.MAPPING, "Mapping source fields to target schema")

    for source_file in migration.files:
        schema = source_file.inferred_schema or {}
        existing = {
            m.source_field: m
            for m in db.query(FieldMapping)
            .filter(FieldMapping.source_file_id == source_file.id)
            .all()
        }

        proposals = []
        for column, profile in schema.items():
            if column in existing and existing[column].decision == str(
                MappingDecision.HUMAN_RESOLVED
            ):
                continue  # a human already decided this one - never re-litigate
            proposals.append(mapping_agent.propose_mapping(column, profile))
        proposals = mapping_agent.resolve_collisions(proposals)

        for proposal in proposals:
            mapping = existing.get(proposal.source_field)
            if mapping is None:
                mapping = FieldMapping(
                    migration_id=migration.id,
                    source_file_id=source_file.id,
                    source_file_name=source_file.filename,
                    source_field=proposal.source_field,
                )
                db.add(mapping)

            mapping.target_field = proposal.target_field
            mapping.confidence = proposal.confidence
            mapping.margin = proposal.margin
            mapping.method = proposal.method
            mapping.ai_assisted = proposal.ai_assisted
            mapping.reason = proposal.reason
            mapping.candidates = proposal.candidates
            mapping.sample_values = proposal.sample_values
            db.flush()

            if proposal.ai_assisted:
                _bump(migration, ai_assisted_decisions=1)

            audit.record(
                db,
                migration,
                AuditEventType.MAPPING_PROPOSED,
                summary=(
                    f"{source_file.filename}: '{proposal.source_field}' -> "
                    f"{proposal.target_field or 'NO TARGET'}"
                ),
                reason=proposal.reason,
                confidence=proposal.confidence,
                ai_assisted=proposal.ai_assisted,
                details={
                    "source_field": proposal.source_field,
                    "target_field": proposal.target_field,
                    "margin": round(proposal.margin, 3),
                    "method": proposal.method,
                    "candidates": proposal.candidates,
                },
            )

            if proposal.auto_apply:
                mapping.decision = str(MappingDecision.AUTO_APPLIED)
                _bump(migration, fields_mapped=1, fields_auto_mapped=1, auto_resolved=1)
                audit.record(
                    db,
                    migration,
                    AuditEventType.MAPPING_AUTO_APPLIED,
                    summary=(
                        f"Applied '{proposal.source_field}' -> {proposal.target_field} "
                        f"automatically ({proposal.confidence:.0%}, margin "
                        f"{proposal.margin:.0%})"
                    ),
                    reason=(
                        "Confidence and margin are both above the autonomy thresholds, and "
                        "the mapping is reversible."
                    ),
                    confidence=proposal.confidence,
                    ai_assisted=proposal.ai_assisted,
                    details={"target_field": proposal.target_field},
                )
            elif proposal.escalate:
                mapping.decision = str(MappingDecision.ESCALATED)
                # The transform phase re-runs after a pause or a human decision.
                # If this column already has an unanswered question in the
                # queue, do not ask it twice.
                already_asked = (
                    db.query(Escalation)
                    .filter(
                        Escalation.migration_id == migration.id,
                        Escalation.type == str(EscalationType.AMBIGUOUS_MAPPING),
                        Escalation.source_file == source_file.filename,
                        Escalation.source_field == proposal.source_field,
                        Escalation.status == str(EscalationStatus.OPEN),
                    )
                    .first()
                )
                if already_asked:
                    already_asked.field_mapping_id = mapping.id
                    db.flush()
                    await asyncio.sleep(0.02)
                    continue

                _bump(migration, fields_escalated=1)
                candidates = [
                    {
                        "value": c["target_field"],
                        "label": c["target_field"],
                        "confidence": c["confidence"],
                        "reason": c["reason"],
                    }
                    for c in proposal.candidates[:3]
                ]
                escalation_service.create(
                    db,
                    migration,
                    type_=EscalationType.AMBIGUOUS_MAPPING,
                    title=f"Ambiguous field mapping: '{proposal.source_field}'",
                    reason=proposal.escalation_reason or proposal.reason,
                    confidence=proposal.confidence,
                    severity=Severity.HIGH,
                    source_file=source_file.filename,
                    source_field=proposal.source_field,
                    candidate_values=candidates,
                    sample_values=proposal.sample_values,
                    field_mapping_id=mapping.id,
                    agent_recommendation=(
                        f"Best guess is {proposal.target_field} at "
                        f"{proposal.confidence:.0%}, but the runner-up is too close to "
                        "decide without you."
                    ),
                )
                audit.record(
                    db,
                    migration,
                    AuditEventType.MAPPING_ESCALATED,
                    summary=f"Escalated mapping for '{proposal.source_field}'",
                    reason=proposal.escalation_reason,
                    confidence=proposal.confidence,
                    details={"candidates": proposal.candidates[:3]},
                )
            else:
                mapping.decision = str(MappingDecision.IGNORED)
                _bump(migration, fields_ignored=1)

            await asyncio.sleep(0.02)
        await _beat(db, migration)


def _mapping_index(db: Session, migration: Migration) -> dict[int, dict[str, FieldMapping]]:
    """{source_file_id: {source_column: mapping}} for applied mappings only."""
    index: dict[int, dict[str, FieldMapping]] = {}
    for mapping in (
        db.query(FieldMapping).filter(FieldMapping.migration_id == migration.id).all()
    ):
        if not mapping.target_field:
            continue
        if mapping.decision == str(MappingDecision.ESCALATED):
            continue  # unresolved - the column is parked, not guessed
        index.setdefault(mapping.source_file_id, {})[mapping.source_field] = mapping
    return index


def _human_overrides(db: Session, migration: Migration) -> dict[int, dict[str, str]]:
    """{employee_record_id: {target_field: corrected value}} from resolved escalations."""
    overrides: dict[int, dict[str, str]] = {}
    resolved = (
        db.query(Escalation)
        .filter(
            Escalation.migration_id == migration.id,
            Escalation.status.in_(
                [str(EscalationStatus.APPROVED), str(EscalationStatus.CORRECTED)]
            ),
        )
        .all()
    )
    for esc in resolved:
        if esc.type == str(EscalationType.AMBIGUOUS_MAPPING):
            continue  # handled at the mapping layer
        value = (esc.resolution or {}).get("value")
        if value is None or not esc.source_field:
            continue
        for record_id in esc.affected_record_ids or []:
            overrides.setdefault(int(record_id), {})[esc.source_field] = value
    return overrides


def _column_hints(db: Session, migration: Migration) -> dict[int, dict[str, dict]]:
    """Per file: {target_field: {day_first: bool}} taken from the column profile."""
    hints: dict[int, dict[str, dict]] = {}
    index = _mapping_index(db, migration)
    for source_file in migration.files:
        schema = source_file.inferred_schema or {}
        file_hints: dict[str, dict] = {}
        for column, mapping in index.get(source_file.id, {}).items():
            profile = schema.get(column, {})
            if "day_first" in profile:
                file_hints[mapping.target_field] = {"day_first": profile["day_first"]}
        hints[source_file.id] = file_hints
    return hints


async def _stage_clean(db: Session, migration: Migration) -> None:
    _set_state(db, migration, MigrationState.CLEANING, "Applying mappings and cleaning values")

    index = _mapping_index(db, migration)
    hints = _column_hints(db, migration)
    overrides = _human_overrides(db, migration)

    source_records = (
        db.query(SourceRecord)
        .filter(SourceRecord.migration_id == migration.id)
        .order_by(SourceRecord.source_file_id, SourceRecord.row_number)
        .all()
    )
    existing = {
        r.source_record_id: r
        for r in db.query(EmployeeRecord)
        .filter(EmployeeRecord.migration_id == migration.id)
        .all()
    }
    files = {f.id: f for f in migration.files}

    migration.progress_total = len(source_records)
    migration.progress_done = 0
    cleaned_values = 0

    for position, source in enumerate(source_records, start=1):
        already = existing.get(source.id)
        if already is not None and already.status in (
            str(RecordStatus.PUSHED),
            str(RecordStatus.ROLLED_BACK),
        ):
            # Never rewrite a record that has already reached the target.
            migration.progress_done = position
            continue
        source_file = files[source.source_file_id]
        file_mappings = index.get(source.source_file_id, {})

        mapped: dict[str, str] = {}
        for column, value in source.raw.items():
            mapping = file_mappings.get(column)
            if mapping and mapping.target_field:
                mapped[mapping.target_field] = value

        transformed, changes, issues = cleaning.clean_record(
            mapped, hints.get(source.source_file_id, {})
        )

        record = existing.get(source.id)
        if record is None:
            record = EmployeeRecord(
                migration_id=migration.id,
                source_file_name=source_file.filename,
                source_row_number=source.row_number,
                source_record_id=source.id,
            )
            db.add(record)
            db.flush()
            existing[source.id] = record

        record.raw = source.raw
        record.mapped = mapped
        record.transformed = transformed
        record.changes = [c.as_dict() for c in changes]
        record.validation_errors = []
        record.repair_attempts = 0
        record.is_duplicate = False
        record.merged_into_id = None
        record.merged_from = []
        record.dedupe_notes = []
        record.status = str(RecordStatus.CLEANED)
        record.employee_id = transformed.get("employee_id")

        # Human corrections from a previous round always win over cleaning.
        for target_field, value in overrides.get(record.id, {}).items():
            before = record.transformed.get(target_field)
            record.transformed = {**record.transformed, target_field: value}
            record.changes = record.changes + [
                {
                    "field": target_field,
                    "before": before,
                    "after": value,
                    "rule": "human_correction",
                    "reversible": True,
                    "actor": "human",
                }
            ]

        cleaned_values += len(changes)
        for change in changes[:4]:
            audit.record(
                db,
                migration,
                AuditEventType.FIELD_CLEANED,
                summary=f"{source_file.filename} row {source.row_number}: "
                f"{change.field} {change.rule}",
                reason=f"Deterministic rule '{change.rule}' - reversible",
                record_ref=record.employee_id,
                before={change.field: change.before},
                after={change.field: change.after},
                details={"rule": change.rule},
                publish=False,
            )
        for issue in issues:
            if issue.safe_to_drop:
                audit.record(
                    db,
                    migration,
                    AuditEventType.VALIDATION_FAILURE,
                    summary=(
                        f"Dropped unparseable optional value "
                        f"{issue.field}='{issue.value}' on row {source.row_number}"
                    ),
                    reason=f"{issue.message}. Optional field, so the record is not blocked.",
                    record_ref=record.employee_id,
                    before={issue.field: issue.value},
                    after={issue.field: None},
                )

        migration.progress_done = position
        if position % 5 == 0 or position == len(source_records):
            _publish_state(migration)
            await _beat(db, migration)

    _bump(migration, values_cleaned=cleaned_values)
    _set_stats(migration, records=len(source_records))
    db.flush()


async def _stage_deduplicate(db: Session, migration: Migration) -> None:
    _set_state(
        db, migration, MigrationState.DEDUPLICATING, "Detecting and reconciling duplicates"
    )

    records = (
        db.query(EmployeeRecord)
        .filter(EmployeeRecord.migration_id == migration.id)
        .order_by(EmployeeRecord.id)
        .all()
    )
    payloads = []
    for r in records:
        payload = dict(r.transformed or {})
        payload["__source_file"] = r.source_file_name
        payload["__row"] = r.source_row_number
        payloads.append(payload)

    precedence = {
        i: SOURCE_PRECEDENCE.get(records[i].source_file_name, 1) for i in range(len(records))
    }
    groups = deduplication.find_duplicate_groups(payloads)
    overrides = _human_overrides(db, migration)

    merged_count, conflict_count = 0, 0
    for group in groups:
        result = deduplication.reconcile_group(payloads, group, precedence)
        survivor = records[result.survivor_index]
        duplicates = [records[i] for i in result.merged_indices]

        audit.record(
            db,
            migration,
            AuditEventType.DUPLICATE_DETECTED,
            summary=(
                f"{len(group)} rows describe the same employee "
                f"({survivor.employee_id or survivor.transformed.get('email')})"
            ),
            reason=f"Matched on {result.match_rule}",
            confidence=result.match_confidence,
            record_ref=survivor.employee_id,
            details={
                "match_rule": result.match_rule,
                "rows": [
                    {"file": records[i].source_file_name, "row": records[i].source_row_number}
                    for i in group
                ],
            },
        )

        blocking_conflicts = [c for c in result.conflicts if c.needs_human]
        merged_values = {
            k: v for k, v in result.merged_values.items() if not k.startswith("__")
        }

        survivor.transformed = {**survivor.transformed, **merged_values}
        survivor.merged_from = [
            {
                "source_file": d.source_file_name,
                "row": d.source_row_number,
                "record_id": d.id,
            }
            for d in duplicates
        ]
        survivor.dedupe_notes = result.notes + [
            f"Matched on {result.match_rule} "
            f"(confidence {result.match_confidence:.0%})"
        ]
        for dup in duplicates:
            dup.status = str(RecordStatus.MERGED)
            dup.is_duplicate = True
            dup.merged_into_id = survivor.id
        merged_count += len(duplicates)

        for conflict in result.conflicts:
            if conflict.needs_human:
                conflict_count += 1
                continue
            audit.record(
                db,
                migration,
                AuditEventType.DUPLICATE_MERGED,
                summary=(
                    f"{survivor.employee_id}: resolved conflicting '{conflict.field_name}' "
                    f"automatically"
                ),
                reason=(
                    f"Non-critical field; kept the value from the higher-precedence source "
                    f"({conflict.resolution_rule})"
                ),
                confidence=conflict.confidence,
                record_ref=survivor.employee_id,
                before={conflict.field_name: [v["value"] for v in conflict.values]},
                after={conflict.field_name: conflict.resolved_value},
            )
            _bump(migration, auto_resolved=1)

        if blocking_conflicts:
            resolved_fields = overrides.get(survivor.id, {})
            # A human decision, once made, is re-applied on top of the merge.
            if resolved_fields:
                survivor.transformed = {**survivor.transformed, **resolved_fields}
            unresolved = [c for c in blocking_conflicts if c.field_name not in resolved_fields]
            existing_fields = {
                e.source_field
                for e in db.query(Escalation)
                .filter(
                    Escalation.migration_id == migration.id,
                    Escalation.type == str(EscalationType.DUPLICATE_CONFLICT),
                    Escalation.record_id == (survivor.employee_id or ""),
                )
                .all()
            }
            unresolved = [c for c in unresolved if c.field_name not in existing_fields]
            if unresolved:
                conflict = unresolved[0]
                escalation_service.create(
                    db,
                    migration,
                    type_=EscalationType.DUPLICATE_CONFLICT,
                    title=(
                        f"Duplicate records disagree on '{conflict.field_name}' "
                        f"for {survivor.employee_id}"
                    ),
                    reason=(
                        f"The same employee appears in "
                        f"{len({v['source_file'] for v in conflict.values})} sources with "
                        f"different values for '{conflict.field_name}'. This field changes "
                        "what the employee can do in the target platform, so the agent will "
                        "not pick a winner."
                    ),
                    confidence=0.0,
                    severity=Severity.MEDIUM,
                    source_field=conflict.field_name,
                    source_value=" / ".join(v["value"] for v in conflict.values),
                    candidate_values=[
                        {
                            "value": v["value"],
                            "label": v["value"],
                            "confidence": 0.5,
                            "reason": f"from {v['source_file']} row {v['row']}",
                        }
                        for v in conflict.values
                    ],
                    record_id=survivor.employee_id,
                    affected_record_ids=[survivor.id],
                    agent_recommendation=(
                        "Both sources are internally consistent; the target platform needs "
                        "one answer."
                    ),
                )
                survivor.status = str(RecordStatus.BLOCKED)

        await asyncio.sleep(0.02)

    _set_stats(
        migration,
        duplicates_found=merged_count,
        duplicates_merged=merged_count,
        duplicate_conflicts=conflict_count,
    )
    db.flush()
    await _beat(db, migration)


def _rejected_record_ids(db: Session, migration: Migration) -> set[int]:
    """Records a human explicitly decided NOT to migrate."""
    rejected: set[int] = set()
    for esc in (
        db.query(Escalation)
        .filter(
            Escalation.migration_id == migration.id,
            Escalation.status == str(EscalationStatus.REJECTED),
        )
        .all()
    ):
        if esc.type == str(EscalationType.AMBIGUOUS_MAPPING):
            continue  # a rejected mapping drops a COLUMN, not a record
        rejected.update(int(i) for i in (esc.affected_record_ids or []))
    return rejected


async def _stage_validate(db: Session, migration: Migration) -> None:
    from . import validation

    _set_state(db, migration, MigrationState.VALIDATING, "Validating against the target schema")

    records = (
        db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.migration_id == migration.id,
            EmployeeRecord.status.notin_(
                [
                    str(RecordStatus.MERGED),
                    str(RecordStatus.PUSHED),
                    str(RecordStatus.ROLLED_BACK),
                ]
            ),
        )
        .order_by(EmployeeRecord.id)
        .all()
    )

    migration.progress_total = len(records)
    migration.progress_done = 0
    ready, invalid = 0, 0
    rejected = _rejected_record_ids(db, migration)

    seen_ids: dict[str, int] = {}

    for position, record in enumerate(records, start=1):
        if record.id in rejected:
            record.status = str(RecordStatus.INVALID)
            record.validation_errors = [
                {
                    "field": "*",
                    "code": "excluded_by_human",
                    "message": "A consultant rejected this record; it will not be migrated",
                    "value": None,
                    "repairable": False,
                }
            ]
            migration.progress_done = position
            continue

        payload = dict(record.transformed or {})
        issues = validation.validate_record(payload)

        attempts = 0
        while issues and attempts < settings.max_auto_repair_attempts:
            repairable = [i for i in issues if i.repairable]
            if not repairable:
                break
            attempts += 1
            payload, applied = validation.attempt_repair(payload, repairable)
            if not applied:
                break
            for fix in applied:
                audit.record(
                    db,
                    migration,
                    AuditEventType.AUTO_REPAIR,
                    summary=f"{record.employee_id}: repaired {fix['field']} ({fix['rule']})",
                    reason=f"Automatic repair attempt {attempts} of "
                    f"{settings.max_auto_repair_attempts}",
                    record_ref=record.employee_id,
                    before={fix["field"]: fix["before"]},
                    after={fix["field"]: fix["after"]},
                )
                record.changes = list(record.changes or []) + [
                    {**fix, "reversible": True, "actor": "agent"}
                ]
                _bump(migration, auto_resolved=1, values_cleaned=1)
            issues = validation.validate_record(payload)

        record.transformed = payload
        record.repair_attempts = attempts
        record.validation_errors = [i.as_dict() for i in issues]

        # Duplicate employee_id that deduplication did not merge is a hard stop.
        emp_id = payload.get("employee_id")
        if emp_id and emp_id in seen_ids:
            issues.append(
                validation.ValidationIssue(
                    field="employee_id",
                    code="duplicate_primary_key",
                    message=f"employee_id '{emp_id}' already used by another record",
                    value=emp_id,
                )
            )
            record.validation_errors = [i.as_dict() for i in issues]
        elif emp_id:
            seen_ids[emp_id] = record.id

        if issues:
            invalid += 1
            record.status = str(RecordStatus.INVALID)
            audit.record(
                db,
                migration,
                AuditEventType.VALIDATION_FAILURE,
                summary=(
                    f"{record.employee_id or record.source_file_name} failed validation after "
                    f"{attempts} repair attempt(s)"
                ),
                reason="; ".join(i.message for i in issues),
                record_ref=record.employee_id,
                details={"errors": record.validation_errors},
            )
            await _escalate_invalid_record(db, migration, record, issues)
        else:
            ready += 1
            if record.status != str(RecordStatus.BLOCKED):
                record.status = str(RecordStatus.READY)

        migration.progress_done = position
        if position % 5 == 0 or position == len(records):
            _publish_state(migration)
            await _beat(db, migration)

    db.flush()
    _set_stats(
        migration,
        ready=sum(1 for r in records if r.status == str(RecordStatus.READY)),
        invalid=sum(1 for r in records if r.status == str(RecordStatus.INVALID)),
        blocked=sum(1 for r in records if r.status == str(RecordStatus.BLOCKED)),
    )
    db.flush()


async def _escalate_invalid_record(
    db: Session, migration: Migration, record: EmployeeRecord, issues: list
) -> None:
    from . import validation  # noqa: F401  (typing only)

    open_for_record = [
        e
        for e in db.query(Escalation)
        .filter(
            Escalation.migration_id == migration.id,
            Escalation.status == str(EscalationStatus.OPEN),
        )
        .all()
        if record.id in (e.affected_record_ids or [])
    ]
    if open_for_record:
        record.status = str(RecordStatus.BLOCKED)
        return

    blocking_issue = next((i for i in issues if i.code == "required_missing"), issues[0])
    is_missing = blocking_issue.code == "required_missing"

    suggestions: list[dict] = []
    if is_missing and blocking_issue.field == "email":
        name = record.transformed.get("full_name")
        if name and not is_blank(name):
            slug = ".".join(str(name).lower().split())
            suggestions.append(
                {
                    "value": f"{slug}@acme-corp.com",
                    "label": f"{slug}@acme-corp.com",
                    "confidence": 0.45,
                    "reason": (
                        "Derived from the employee name using the domain pattern seen in the "
                        "rest of the file. The agent will NOT apply this on its own - a "
                        "wrong email is an onboarding failure, and it is not reversible "
                        "once the welcome mail goes out."
                    ),
                }
            )

    record.status = str(RecordStatus.BLOCKED)
    escalation_service.create(
        db,
        migration,
        type_=(
            EscalationType.MISSING_MANDATORY_FIELD
            if is_missing
            else EscalationType.VALIDATION_FAILURE
        ),
        title=(
            f"Mandatory field '{blocking_issue.field}' is missing for "
            f"{record.employee_id or 'an unidentified row'}"
            if is_missing
            else f"{record.employee_id}: {blocking_issue.message}"
        ),
        reason=(
            f"{blocking_issue.message}. The agent made {record.repair_attempts} automatic "
            f"repair attempt(s) (limit {settings.max_auto_repair_attempts}) and could not "
            "resolve it from the source data."
        ),
        confidence=0.0,
        severity=Severity.HIGH if is_missing else Severity.MEDIUM,
        source_file=record.source_file_name,
        source_field=blocking_issue.field,
        source_value=blocking_issue.value,
        candidate_values=suggestions,
        sample_values=[
            f"{k}={v}" for k, v in (record.transformed or {}).items() if v
        ][:6],
        record_id=record.employee_id,
        affected_record_ids=[record.id],
        agent_recommendation=(
            "No safe automatic value exists. A consultant must supply or confirm it."
            if not suggestions
            else "A pattern-based suggestion is offered, but it is a guess - please confirm."
        ),
    )


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
#: Counters that describe the CURRENT transform run, not a running total.
#: They are reset on every re-run so the dashboard never double counts after a
#: human decision sends the agent round again.
_PER_RUN_COUNTERS = (
    "fields_mapped",
    "fields_auto_mapped",
    "fields_ignored",
    "values_cleaned",
    "auto_resolved",
    "duplicates_found",
    "duplicates_merged",
)


async def _transform_phase(db: Session, migration: Migration) -> None:
    _set_stats(migration, **{key: 0 for key in _PER_RUN_COUNTERS})
    await _stage_profile(db, migration)
    await _stage_map(db, migration)
    await _stage_clean(db, migration)
    await _stage_deduplicate(db, migration)
    await _stage_validate(db, migration)


def _refresh_escalation_stats(db: Session, migration: Migration) -> int:
    total = (
        db.query(Escalation).filter(Escalation.migration_id == migration.id).count()
    )
    open_items = escalation_service.open_escalations(db, migration)
    _set_stats(
        migration, escalations_total=total, escalations_open=len(open_items)
    )
    return len(open_items)


async def _settle(db: Session, migration: Migration) -> bool:
    """After the transform phase decide: wait for a human, or push. True = ready."""
    open_count = _refresh_escalation_stats(db, migration)
    if open_count:
        _set_state(
            db,
            migration,
            MigrationState.WAITING_FOR_HUMAN,
            f"{open_count} escalation(s) need a decision before the push can start",
        )
        db.commit()
        return False

    ready = (
        db.query(EmployeeRecord)
        .filter(
            EmployeeRecord.migration_id == migration.id,
            EmployeeRecord.status == str(RecordStatus.READY),
        )
        .count()
    )
    _set_state(
        db,
        migration,
        MigrationState.READY_TO_PUSH,
        f"{ready} record(s) validated and ready for the target platform",
        total=ready,
        done=0,
    )
    db.commit()
    return True


async def _run_pipeline(migration_ref: str, *, auto_push: bool) -> None:
    try:
        with session_scope() as db:
            migration = get_migration(db, migration_ref)
            if migration.started_at is None:
                migration.started_at = utcnow()
                audit.record(
                    db,
                    migration,
                    AuditEventType.MIGRATION_STARTED,
                    summary=f"Agent started migration {migration.migration_id}",
                    details={
                        "mode": migration.mode,
                        "llm_provider": migration.llm_provider,
                        "thresholds": {
                            "high": settings.high_confidence_threshold,
                            "medium": settings.medium_confidence_threshold,
                            "margin": settings.min_confidence_margin,
                        },
                    },
                )
            _set_state(
                db, migration, MigrationState.DISCOVERING, "Reading source files"
            )
            db.commit()

            await _transform_phase(db, migration)
            ready = await _settle(db, migration)

        if ready and auto_push:
            await push_migration(migration_ref)
    except PausedSignal:
        log.info("migration_paused", migration_id=migration_ref)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("migration_failed", migration_id=migration_ref)
        with session_scope() as db:
            migration = get_migration(db, migration_ref)
            migration.error = f"{type(exc).__name__}: {exc}"
            _set_state(db, migration, MigrationState.FAILED, "Agent stopped with an error")
            audit.record(
                db,
                migration,
                AuditEventType.ERROR,
                summary="Migration failed",
                reason=str(exc),
                details={"exception": type(exc).__name__},
            )
    finally:
        _running.pop(migration_ref, None)


async def _resume_pipeline(migration_ref: str, *, auto_push: bool) -> None:
    """Re-run the transform phase now that human decisions are known."""
    try:
        with session_scope() as db:
            migration = get_migration(db, migration_ref)
            _apply_mapping_resolutions(db, migration)
            _set_state(
                db,
                migration,
                MigrationState.MAPPING,
                "Human decisions applied - re-running the transform pipeline",
            )
            db.commit()
            await _transform_phase(db, migration)
            ready = await _settle(db, migration)

        if ready and auto_push:
            await push_migration(migration_ref)
    except PausedSignal:
        log.info("migration_paused", migration_id=migration_ref)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("resume_failed", migration_id=migration_ref)
        with session_scope() as db:
            migration = get_migration(db, migration_ref)
            migration.error = f"{type(exc).__name__}: {exc}"
            _set_state(db, migration, MigrationState.FAILED, "Agent stopped with an error")
    finally:
        _running.pop(migration_ref, None)


def _apply_mapping_resolutions(db: Session, migration: Migration) -> None:
    """Write resolved AMBIGUOUS_MAPPING decisions back onto the FieldMapping rows."""
    resolved = (
        db.query(Escalation)
        .filter(
            Escalation.migration_id == migration.id,
            Escalation.type == str(EscalationType.AMBIGUOUS_MAPPING),
            Escalation.status.in_(
                [
                    str(EscalationStatus.APPROVED),
                    str(EscalationStatus.CORRECTED),
                    str(EscalationStatus.REJECTED),
                ]
            ),
        )
        .all()
    )
    for esc in resolved:
        if not esc.field_mapping_id:
            continue
        mapping = db.get(FieldMapping, esc.field_mapping_id)
        if mapping is None or mapping.decision == str(MappingDecision.HUMAN_RESOLVED):
            continue
        if esc.status == str(EscalationStatus.REJECTED):
            mapping.target_field = None
            mapping.decision = str(MappingDecision.IGNORED)
            mapping.reason = "Rejected by a human - column excluded from the migration"
        else:
            chosen = (esc.resolution or {}).get("value")
            mapping.target_field = chosen
            mapping.decision = str(MappingDecision.HUMAN_RESOLVED)
            mapping.confidence = 1.0
            mapping.margin = 1.0
            mapping.method = "human_decision"
            mapping.reason = (
                f"Chosen by {esc.resolved_by} after the agent flagged the column as ambiguous"
            )
        mapping.resolved_by = esc.resolved_by
        db.flush()


# ---------------------------------------------------------------------------
# public entry points
# ---------------------------------------------------------------------------
def start(migration_ref: str, *, auto_push: bool | None = None) -> None:
    if migration_ref in _running:
        raise InvalidStateError(f"Migration {migration_ref} is already running")
    auto_push = settings.auto_push_after_resolution if auto_push is None else auto_push
    _spawn(migration_ref, _run_pipeline(migration_ref, auto_push=auto_push))


def resume(migration_ref: str, *, auto_push: bool | None = None) -> None:
    if migration_ref in _running:
        raise InvalidStateError(f"Migration {migration_ref} is already running")
    auto_push = settings.auto_push_after_resolution if auto_push is None else auto_push
    _spawn(migration_ref, _resume_pipeline(migration_ref, auto_push=auto_push))


def is_running(migration_ref: str) -> bool:
    return migration_ref in _running


async def push_migration(migration_ref: str, *, only_failed: bool = False) -> dict:
    """Push READY records (or retry FAILED ones) to the mock target platform."""
    with session_scope() as db:
        migration = get_migration(db, migration_ref)
        wanted = str(RecordStatus.FAILED) if only_failed else str(RecordStatus.READY)
        records = (
            db.query(EmployeeRecord)
            .filter(
                EmployeeRecord.migration_id == migration.id,
                EmployeeRecord.status == wanted,
            )
            .order_by(EmployeeRecord.id)
            .all()
        )
        if only_failed:
            records = [r for r in records if r.push_failure_kind != "permanent"]

        _set_state(
            db,
            migration,
            MigrationState.PUSHING,
            ("Retrying failed records" if only_failed else "Pushing records to the target"),
            total=len(records),
            done=0,
        )
        db.commit()

        succeeded, failed = 0, 0
        for position, record in enumerate(records, start=1):
            ok = await retry_service.push_record(db, migration, record)
            succeeded += int(ok)
            failed += int(not ok)
            migration.progress_done = position
            db.commit()
            _publish_state(migration)

        totals = _recount_push_totals(db, migration)
        migration.completed_at = utcnow()
        _set_state(
            db,
            migration,
            MigrationState.COMPLETED,
            (
                f"Migration complete - {totals['pushed']} in the target platform, "
                f"{totals['failed']} failed, {totals['blocked']} still blocked"
            ),
            total=max(len(records), 1),
            done=len(records),
        )
        audit.record(
            db,
            migration,
            AuditEventType.MIGRATION_STATE_CHANGED,
            summary=(
                f"Push finished: {succeeded} succeeded, {failed} failed in this run"
            ),
            details=totals,
        )
        db.commit()
        return {"succeeded": succeeded, "failed": failed, **totals}


def _recount_push_totals(db: Session, migration: Migration) -> dict:
    def count(status: RecordStatus) -> int:
        return (
            db.query(EmployeeRecord)
            .filter(
                EmployeeRecord.migration_id == migration.id,
                EmployeeRecord.status == str(status),
            )
            .count()
        )

    totals = {
        "pushed": count(RecordStatus.PUSHED),
        "failed": count(RecordStatus.FAILED),
        "ready": count(RecordStatus.READY),
        "invalid": count(RecordStatus.INVALID),
        "blocked": count(RecordStatus.BLOCKED),
        "rolled_back": count(RecordStatus.ROLLED_BACK),
    }
    _set_stats(migration, **totals)
    db.flush()
    return totals


def schedule_push(migration_ref: str, *, only_failed: bool = False) -> None:
    if migration_ref in _running:
        raise InvalidStateError(f"Migration {migration_ref} is already running")
    _spawn(migration_ref, _guarded_push(migration_ref, only_failed=only_failed))


async def _guarded_push(migration_ref: str, *, only_failed: bool) -> None:
    try:
        await push_migration(migration_ref, only_failed=only_failed)
    except Exception:  # pragma: no cover - defensive
        log.exception("push_failed", migration_id=migration_ref)
    finally:
        _running.pop(migration_ref, None)
