"""End-to-end: files -> mapping -> cleaning -> escalation -> human decision
-> revalidation -> target push -> retry -> rollback.

This is the test that proves the pieces actually compose.
"""
from __future__ import annotations

import asyncio

import pytest

from app.database import reset_db, session_scope
from app.models import (
    EmployeeRecord,
    Escalation,
    EscalationStatus,
    EscalationType,
    FieldMapping,
    MappingDecision,
    MigrationState,
    PushAttempt,
    RecordStatus,
    TargetEmployee,
)
from app.services import escalation as escalation_service
from app.services import migration_agent, rollback

CONSULTANT = "test_consultant"


async def _drain(migration_ref: str) -> None:
    """Wait for whatever the agent is currently doing."""
    for _ in range(200):
        task = migration_agent._running.get(migration_ref)
        if task is None:
            await asyncio.sleep(0)
            if migration_ref not in migration_agent._running:
                return
            continue
        await task
    raise AssertionError("agent did not settle")


async def _run_demo() -> str:
    with session_scope() as db:
        migration = migration_agent.create_migration(
            db, name="e2e", file_paths=migration_agent.demo_file_paths()
        )
        ref = migration.migration_id
    migration_agent.start(ref, auto_push=False)
    await _drain(ref)
    return ref


@pytest.fixture
def migration_ref():
    reset_db()
    return asyncio.run(_run_demo())


def test_agent_halts_with_exactly_the_expected_escalations(migration_ref):
    with session_scope() as db:
        migration = migration_agent.get_migration(db, migration_ref)
        assert migration.state == str(MigrationState.WAITING_FOR_HUMAN)

        escalations = db.query(Escalation).filter(
            Escalation.migration_id == migration.id
        ).all()
        types = sorted(e.type for e in escalations)
        assert types == [
            str(EscalationType.AMBIGUOUS_MAPPING),
            str(EscalationType.DUPLICATE_CONFLICT),
            str(EscalationType.MISSING_MANDATORY_FIELD),
        ]
        assert all(e.status == str(EscalationStatus.OPEN) for e in escalations)


def test_autonomy_ratio_is_heavily_weighted_to_the_agent(migration_ref):
    with session_scope() as db:
        migration = migration_agent.get_migration(db, migration_ref)
        stats = migration.stats

        assert stats["files"] == 2
        assert stats["source_rows"] == 33
        assert stats["fields_auto_mapped"] >= 17
        assert stats["fields_escalated"] == 1
        assert stats["values_cleaned"] > 50
        assert stats["duplicates_merged"] == 7
        # Far more decisions made alone than handed over.
        assert stats["auto_resolved"] > 10 * stats["escalations_total"] / 3


def test_deterministic_cleaning_happened_without_escalation(migration_ref):
    with session_scope() as db:
        migration = migration_agent.get_migration(db, migration_ref)
        record = (
            db.query(EmployeeRecord)
            .filter(
                EmployeeRecord.migration_id == migration.id,
                EmployeeRecord.employee_id == "EMP1001",
                EmployeeRecord.status != str(RecordStatus.MERGED),
            )
            .first()
        )
        assert record is not None
        assert record.transformed["full_name"] == "Rajesh Kumar"
        assert record.transformed["email"] == "rajesh.kumar@acme-corp.com"
        assert record.transformed["date_of_birth"] == "1988-08-12"
        assert record.transformed["status"] == "active"
        assert all(c["reversible"] for c in record.changes)


def test_unparseable_optional_date_is_dropped_not_escalated(migration_ref):
    with session_scope() as db:
        migration = migration_agent.get_migration(db, migration_ref)
        record = (
            db.query(EmployeeRecord)
            .filter(
                EmployeeRecord.migration_id == migration.id,
                EmployeeRecord.employee_id == "EMP1004",
            )
            .first()
        )
        assert record.transformed["date_of_birth"] is None
        assert record.status == str(RecordStatus.READY)  # not blocked


def test_missing_email_is_auto_filled_from_the_other_file(migration_ref):
    """EMP1031 has no email in the CSV but does in the XLSX - no human needed."""
    with session_scope() as db:
        migration = migration_agent.get_migration(db, migration_ref)
        survivor = (
            db.query(EmployeeRecord)
            .filter(
                EmployeeRecord.migration_id == migration.id,
                EmployeeRecord.employee_id == "EMP1031",
                EmployeeRecord.status != str(RecordStatus.MERGED),
            )
            .first()
        )
        assert survivor.transformed["email"] == "ananya.desai@acme-corp.com"
        assert not any(
            e.record_id == "EMP1031"
            for e in db.query(Escalation).filter(Escalation.migration_id == migration.id)
        )


def test_full_lifecycle_through_human_resolution_push_retry_and_rollback(migration_ref):
    async def scenario():
        # ---- human resolves every escalation ---------------------------
        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            for esc in escalation_service.open_escalations(db, migration):
                if esc.type == str(EscalationType.AMBIGUOUS_MAPPING):
                    value = "mobile_phone"
                elif esc.type == str(EscalationType.DUPLICATE_CONFLICT):
                    value = "inactive"
                else:
                    value = "karan.malhotra@acme-corp.com"
                escalation_service.resolve(
                    db,
                    esc,
                    decision=EscalationStatus.CORRECTED,
                    chosen_value=value,
                    note="resolved in test",
                    resolved_by=CONSULTANT,
                )

        # ---- agent resumes, revalidates and pushes ---------------------
        migration_agent.resume(migration_ref, auto_push=True)
        await _drain(migration_ref)

        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            assert migration.state == str(MigrationState.COMPLETED)

            # the human mapping decision was applied to the FieldMapping row
            mapping = (
                db.query(FieldMapping)
                .filter(
                    FieldMapping.migration_id == migration.id,
                    FieldMapping.source_field == "Contact No",
                )
                .one()
            )
            assert mapping.target_field == "mobile_phone"
            assert mapping.decision == str(MappingDecision.HUMAN_RESOLVED)
            assert mapping.resolved_by == CONSULTANT

            def record(emp_id: str) -> EmployeeRecord:
                return (
                    db.query(EmployeeRecord)
                    .filter(
                        EmployeeRecord.migration_id == migration.id,
                        EmployeeRecord.employee_id == emp_id,
                        EmployeeRecord.status != str(RecordStatus.MERGED),
                    )
                    .one()
                )

            # human corrections survived the re-run of the whole pipeline
            assert record("EMP1042").transformed["email"] == "karan.malhotra@acme-corp.com"
            assert record("EMP1017").transformed["status"] == "inactive"
            # the resolved mapping is now actually used
            assert record("EMP1001").transformed["mobile_phone"] == "+919876543210"

            # transient failure recovered automatically inside the first push
            emp1009 = [
                (a.attempt, a.status)
                for a in db.query(PushAttempt)
                .filter(PushAttempt.employee_id == "EMP1009")
                .order_by(PushAttempt.attempt)
                .all()
            ]
            assert emp1009[-1][1] == "success"
            assert len(emp1009) > 1

            # permanent rejection stays failed
            assert record("EMP1011").status == str(RecordStatus.FAILED)
            assert record("EMP1011").push_failure_kind == "permanent"

            pushed_before_retry = migration.stats["pushed"]

        # ---- retry the retryable failure -------------------------------
        migration_agent.schedule_push(migration_ref, only_failed=True)
        await _drain(migration_ref)

        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            assert migration.stats["pushed"] == pushed_before_retry + 1
            assert migration.stats["failed"] == 1  # only the permanent one remains

            in_target = db.query(TargetEmployee).count()
            assert in_target == migration.stats["pushed"]

        # ---- rollback ---------------------------------------------------
        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            result = rollback.rollback_migration(db, migration, actor_name=CONSULTANT)
            assert result["failed"] == 0
            assert migration.state == str(MigrationState.ROLLED_BACK)

        with session_scope() as db:
            assert db.query(TargetEmployee).count() == 0

    asyncio.run(scenario())


def test_rejecting_an_escalation_excludes_the_record(migration_ref):
    async def scenario():
        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            for esc in escalation_service.open_escalations(db, migration):
                if esc.type == str(EscalationType.MISSING_MANDATORY_FIELD):
                    escalation_service.resolve(
                        db,
                        esc,
                        decision=EscalationStatus.REJECTED,
                        chosen_value=None,
                        note="not a real employee",
                        resolved_by=CONSULTANT,
                    )
                else:
                    escalation_service.resolve(
                        db,
                        esc,
                        decision=EscalationStatus.APPROVED,
                        chosen_value=esc.candidate_values[0]["value"],
                        resolved_by=CONSULTANT,
                    )

        migration_agent.resume(migration_ref, auto_push=False)
        await _drain(migration_ref)

        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            rejected = (
                db.query(EmployeeRecord)
                .filter(
                    EmployeeRecord.migration_id == migration.id,
                    EmployeeRecord.employee_id == "EMP1042",
                )
                .one()
            )
            assert rejected.status == str(RecordStatus.INVALID)
            assert rejected.validation_errors[0]["code"] == "excluded_by_human"
            # and the agent did not re-raise the same escalation
            assert not escalation_service.open_escalations(db, migration)

    asyncio.run(scenario())


def test_audit_trail_separates_agent_and_human_actions(migration_ref):
    from app.models import Actor, AuditEvent, AuditEventType

    async def scenario():
        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            esc = escalation_service.open_escalations(db, migration)[0]
            escalation_service.resolve(
                db,
                esc,
                decision=EscalationStatus.APPROVED,
                chosen_value=esc.candidate_values[0]["value"],
                note="audited",
                resolved_by=CONSULTANT,
            )

        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            events = db.query(AuditEvent).filter(
                AuditEvent.migration_id == migration.id
            ).all()

            agent_events = [e for e in events if e.actor == str(Actor.AGENT)]
            human_events = [e for e in events if e.actor == str(Actor.HUMAN)]

            assert len(agent_events) > 100
            assert len(human_events) == 1
            assert human_events[0].event == str(AuditEventType.HUMAN_DECISION)
            assert human_events[0].actor_name == CONSULTANT
            # every mapping decision carries its confidence and its reason
            mappings = [
                e for e in events if e.event == str(AuditEventType.MAPPING_PROPOSED)
            ]
            assert mappings and all(m.confidence is not None and m.reason for m in mappings)

    asyncio.run(scenario())


def test_rerunning_the_pipeline_does_not_duplicate_open_escalations(migration_ref):
    """A pause/resume (or any re-run) must not ask the same question twice."""

    async def scenario():
        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            before = [
                (e.type, e.source_field, e.record_id)
                for e in db.query(Escalation)
                .filter(Escalation.migration_id == migration.id)
                .all()
            ]

        # Re-run the transform phase with nothing resolved.
        migration_agent.resume(migration_ref, auto_push=False)
        await _drain(migration_ref)

        with session_scope() as db:
            migration = migration_agent.get_migration(db, migration_ref)
            after = [
                (e.type, e.source_field, e.record_id)
                for e in db.query(Escalation)
                .filter(Escalation.migration_id == migration.id)
                .all()
            ]
            assert sorted(after) == sorted(before)
            assert migration.stats["fields_escalated"] == 1
            assert migration.state == str(MigrationState.WAITING_FOR_HUMAN)

    asyncio.run(scenario())


def test_per_run_counters_do_not_double_count_after_a_rerun(migration_ref):
    with session_scope() as db:
        first = dict(migration_agent.get_migration(db, migration_ref).stats)

    async def scenario():
        migration_agent.resume(migration_ref, auto_push=False)
        await _drain(migration_ref)

    asyncio.run(scenario())

    with session_scope() as db:
        second = migration_agent.get_migration(db, migration_ref).stats

    for key in ("values_cleaned", "duplicates_merged", "fields_auto_mapped"):
        assert second[key] == first[key], f"{key} double counted on re-run"
