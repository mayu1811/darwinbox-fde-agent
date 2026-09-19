"""Enumerations shared by the persistence layer, the API and the agent."""
from __future__ import annotations

from enum import StrEnum


class MigrationState(StrEnum):
    CREATED = "CREATED"
    DISCOVERING = "DISCOVERING"
    PROFILING = "PROFILING"
    MAPPING = "MAPPING"
    CLEANING = "CLEANING"
    DEDUPLICATING = "DEDUPLICATING"
    VALIDATING = "VALIDATING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    READY_TO_PUSH = "READY_TO_PUSH"
    PUSHING = "PUSHING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


#: States from which the agent can be resumed by a human.
PAUSED_STATES = {MigrationState.PAUSED, MigrationState.WAITING_FOR_HUMAN}
TERMINAL_STATES = {MigrationState.COMPLETED, MigrationState.FAILED, MigrationState.ROLLED_BACK}


class RecordStatus(StrEnum):
    PENDING = "PENDING"          # ingested, not yet transformed
    CLEANED = "CLEANED"          # normalised, awaiting validation
    MERGED = "MERGED"            # absorbed into another record by deduplication
    BLOCKED = "BLOCKED"          # waiting on a human escalation
    INVALID = "INVALID"          # failed validation, cannot be auto-repaired
    READY = "READY"              # valid and ready to push
    PUSHED = "PUSHED"            # accepted by the target API
    FAILED = "FAILED"            # rejected by the target API
    ROLLED_BACK = "ROLLED_BACK"  # removed from the target API


class MappingDecision(StrEnum):
    AUTO_APPLIED = "AUTO_APPLIED"
    ESCALATED = "ESCALATED"
    HUMAN_RESOLVED = "HUMAN_RESOLVED"
    IGNORED = "IGNORED"          # source field with no meaningful target


class EscalationType(StrEnum):
    AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
    MISSING_MANDATORY_FIELD = "MISSING_MANDATORY_FIELD"
    UNSAFE_VALUE = "UNSAFE_VALUE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    DESTRUCTIVE_ACTION = "DESTRUCTIVE_ACTION"


class EscalationStatus(StrEnum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Actor(StrEnum):
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM = "system"
    TARGET_API = "target_api"


class AuditEventType(StrEnum):
    MIGRATION_CREATED = "MIGRATION_CREATED"
    MIGRATION_STARTED = "MIGRATION_STARTED"
    MIGRATION_STATE_CHANGED = "MIGRATION_STATE_CHANGED"
    FILE_UPLOADED = "FILE_UPLOADED"
    SCHEMA_INFERRED = "SCHEMA_INFERRED"
    MAPPING_PROPOSED = "MAPPING_PROPOSED"
    MAPPING_AUTO_APPLIED = "MAPPING_AUTO_APPLIED"
    MAPPING_ESCALATED = "MAPPING_ESCALATED"
    FIELD_CLEANED = "FIELD_CLEANED"
    DUPLICATE_DETECTED = "DUPLICATE_DETECTED"
    DUPLICATE_MERGED = "DUPLICATE_MERGED"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    AUTO_REPAIR = "AUTO_REPAIR"
    ESCALATION_CREATED = "ESCALATION_CREATED"
    HUMAN_DECISION = "HUMAN_DECISION"
    RECORD_PUSHED = "RECORD_PUSHED"
    API_FAILURE = "API_FAILURE"
    RETRY = "RETRY"
    ROLLBACK = "ROLLBACK"
    ERROR = "ERROR"


#: Coarse buckets used by the audit-trail filter in the UI.
AUDIT_CATEGORIES: dict[str, set[str]] = {
    "mappings": {
        AuditEventType.MAPPING_PROPOSED,
        AuditEventType.MAPPING_AUTO_APPLIED,
        AuditEventType.MAPPING_ESCALATED,
        AuditEventType.SCHEMA_INFERRED,
    },
    "transformations": {
        AuditEventType.FIELD_CLEANED,
        AuditEventType.DUPLICATE_DETECTED,
        AuditEventType.DUPLICATE_MERGED,
        AuditEventType.AUTO_REPAIR,
    },
    "errors": {
        AuditEventType.VALIDATION_FAILURE,
        AuditEventType.API_FAILURE,
        AuditEventType.ERROR,
    },
    "api": {
        AuditEventType.RECORD_PUSHED,
        AuditEventType.API_FAILURE,
        AuditEventType.RETRY,
    },
    "rollback": {AuditEventType.ROLLBACK},
    "escalations": {AuditEventType.ESCALATION_CREATED, AuditEventType.HUMAN_DECISION},
}


class PushStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"


class FailureKind(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
