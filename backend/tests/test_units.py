"""Unit tests for the deterministic building blocks of the agent."""
from __future__ import annotations

import pytest

from app.config import DATA_DIR, settings
from app.services import (
    cleaning,
    deduplication,
    ingestion,
    mapping_agent,
    schema_inference,
    validation,
)
from app.utils.dates import detect_day_first, parse_date
from app.utils.text import normalise_email, normalise_person_name, normalise_phone, slugify


# --------------------------------------------------------------- ingestion
def test_csv_ingestion_reads_every_row_verbatim():
    parsed = ingestion.ingest_file(DATA_DIR / "employees_legacy.csv")

    assert parsed["file_type"] == "csv"
    assert parsed["rows"], "expected data rows"
    assert "Emp ID" in parsed["columns"]
    # whitespace must survive ingestion - the audit trail needs the true "before"
    first = parsed["rows"][0]["raw"]
    assert first["Employee Name"] == "  Rajesh  Kumar "
    assert first["Email Address"].endswith(" ")


def test_excel_ingestion():
    parsed = ingestion.ingest_file(DATA_DIR / "employees_hr.xlsx")

    assert parsed["file_type"] == "excel"
    assert "employee_code" in parsed["columns"]
    assert len(parsed["rows"]) == 15


def test_unsupported_file_type_is_rejected(tmp_path):
    bad = tmp_path / "payload.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(Exception) as exc:
        ingestion.ingest_file(bad)
    assert "Unsupported file type" in str(exc.value)


# ----------------------------------------------------------------- dates
@pytest.mark.parametrize(
    "value,day_first,expected",
    [
        ("12/08/2025", True, "2025-08-12"),
        ("2015-04-01", True, "2015-04-01"),
        ("12-Aug-2019", True, "2019-08-12"),
        ("23/07/1991", True, "1991-07-23"),
    ],
)
def test_date_normalisation(value, day_first, expected):
    assert parse_date(value, day_first=day_first).iso == expected


def test_impossible_date_is_not_silently_coerced():
    result = parse_date("31/02/1990", day_first=True)
    assert not result.ok
    assert "invalid calendar date" in (result.error or "")


def test_day_first_detection_uses_column_evidence():
    assert detect_day_first(["12/08/2025", "23/07/1991"]) is True   # 23 > 12
    assert detect_day_first(["08/23/2025", "07/04/1991"]) is False  # 23 in slot 2


# --------------------------------------------------------------- cleaning
def test_text_primitives():
    assert normalise_person_name("  JOHN   DOE ") == "John Doe"
    assert normalise_email("  JOHN@EXAMPLE.COM ") == "john@example.com"
    assert normalise_phone("+91 98765 43210") == "+919876543210"
    assert normalise_phone("9876543211") == "+919876543211"
    assert normalise_phone("12") is None  # too short to normalise safely
    assert slugify("joiningDate") == "joining date"


def test_clean_record_records_every_change():
    cleaned, changes, issues = cleaning.clean_record(
        {
            "employee_id": "emp1001",
            "full_name": " RAJESH  KUMAR ",
            "email": "RAJESH.KUMAR@ACME-CORP.COM ",
            "mobile_phone": "+91 98765 43210",
            "date_of_birth": "12/08/1988",
            "status": "Active",
        },
        {"date_of_birth": {"day_first": True}},
    )

    assert cleaned["full_name"] == "Rajesh Kumar"
    assert cleaned["email"] == "rajesh.kumar@acme-corp.com"
    assert cleaned["date_of_birth"] == "1988-08-12"
    assert cleaned["status"] == "active"
    assert cleaned["employee_id"] == "EMP1001"
    assert issues == []
    rules = {c.rule for c in changes}
    assert {"trim_whitespace", "lowercase_email", "normalise_enum"} <= rules
    assert all(c.reversible for c in changes)


def test_unparseable_optional_value_is_flagged_not_guessed():
    _, _, issues = cleaning.clean_record({"date_of_birth": "31/02/1990"})
    assert len(issues) == 1
    assert issues[0].safe_to_drop is True  # optional field -> drop, do not block


def test_unknown_enum_is_never_guessed():
    cleaned, _, issues = cleaning.clean_record({"status": "on sabbatical"})
    assert cleaned["status"] is None
    assert issues[0].safe_to_drop is False


# ---------------------------------------------------------------- mapping
def _profile(column: str, values: list[str]) -> dict:
    return schema_inference.profile_column(column, values)


def test_high_confidence_mapping_is_applied_automatically():
    proposal = mapping_agent.propose_mapping(
        "DOB", _profile("DOB", ["12/08/1988", "23/07/1991", "05/11/1985"]), use_llm=False
    )
    assert proposal.target_field == "date_of_birth"
    assert proposal.confidence >= settings.high_confidence_threshold
    assert proposal.auto_apply is True
    assert proposal.escalate is False


def test_ambiguous_phone_column_is_escalated_not_guessed():
    proposal = mapping_agent.propose_mapping(
        "Contact No",
        _profile("Contact No", ["9876543210", "9876543211", "9876543212"]),
        use_llm=False,
    )
    assert proposal.escalate is True
    assert proposal.auto_apply is False
    assert proposal.margin < settings.min_confidence_margin
    targets = {c["target_field"] for c in proposal.candidates[:2]}
    assert targets == {"mobile_phone", "work_phone"}


def test_column_with_no_target_is_left_unmapped():
    proposal = mapping_agent.propose_mapping(
        "Remarks", _profile("Remarks", ["migrated from AS400", "check DOB"]), use_llm=False
    )
    assert proposal.target_field is None
    assert proposal.escalate is False  # not an escalation, just not migrated


def test_medium_confidence_on_a_mandatory_field_escalates():
    """Medium confidence is not enough for a field the target requires."""
    profile = _profile("employee no", ["EMP1", "EMP2", "EMP3"])
    proposal = mapping_agent.propose_mapping("employee no", profile, use_llm=False)

    assert proposal.target_field == "employee_id"
    assert (
        settings.medium_confidence_threshold
        <= proposal.confidence
        < settings.high_confidence_threshold
    )
    assert proposal.auto_apply is False
    assert proposal.escalate is True


def test_medium_confidence_on_an_optional_field_is_applied_automatically():
    """The same confidence band, but a non-critical field and a clear margin."""
    profile = _profile("work number", ["2212345678", "2212345679"])
    proposal = mapping_agent.propose_mapping("work number", profile, use_llm=False)

    assert proposal.target_field == "work_phone"
    assert proposal.margin >= settings.min_confidence_margin
    assert proposal.auto_apply is True


def test_collision_resolution_keeps_one_column_per_target():
    proposals = [
        mapping_agent.propose_mapping("full name", _profile("full name", ["A B"]), use_llm=False),
        mapping_agent.propose_mapping(
            "display name", _profile("display name", ["A B"]), use_llm=False
        ),
    ]
    resolved = mapping_agent.resolve_collisions(proposals)
    targets = [p.target_field for p in resolved if p.target_field]
    assert len(targets) == len(set(targets)), "a target field was claimed twice"


# ------------------------------------------------------------ deduplication
def _rec(**kw):
    base = {"__source_file": kw.pop("file", "a.csv"), "__row": kw.pop("row", 2)}
    return {**base, **kw}


def test_duplicates_matched_on_employee_id_and_email():
    records = [
        _rec(employee_id="EMP1", email="a@x.com", full_name="A"),
        _rec(employee_id="EMP1", email="a@x.com", full_name="A", file="b.xlsx"),
        _rec(employee_id="EMP2", email="b@x.com", full_name="B"),
        _rec(employee_id=None, email="b@x.com", full_name="B", file="b.xlsx"),
    ]
    groups = deduplication.find_duplicate_groups(records)
    assert sorted(len(g) for g in groups) == [2, 2]


def test_identical_duplicates_merge_without_a_human():
    records = [
        _rec(employee_id="EMP1", email="a@x.com", full_name="A", department="Engineering"),
        _rec(employee_id="EMP1", email="a@x.com", full_name="A", department="Engineering"),
    ]
    result = deduplication.reconcile_group(records, [0, 1], {0: 1, 1: 1})
    assert result.conflicts == []
    assert result.merged_values["department"] == "Engineering"


def test_non_critical_conflict_is_resolved_by_source_precedence():
    records = [
        _rec(employee_id="EMP1", email="a@x.com", designation="Brand Manager"),
        _rec(employee_id="EMP1", email="a@x.com", designation="Senior Brand Manager",
             file="hr.xlsx"),
    ]
    result = deduplication.reconcile_group(records, [0, 1], {0: 1, 1: 2})
    conflict = next(c for c in result.conflicts if c.field_name == "designation")
    assert conflict.needs_human is False
    assert result.merged_values["designation"] == "Senior Brand Manager"


def test_critical_conflict_requires_a_human():
    records = [
        _rec(employee_id="EMP1", email="a@x.com", status="active"),
        _rec(employee_id="EMP1", email="a@x.com", status="inactive", file="hr.xlsx"),
    ]
    result = deduplication.reconcile_group(records, [0, 1], {0: 1, 1: 2})
    conflict = next(c for c in result.conflicts if c.field_name == "status")
    assert conflict.needs_human is True


def test_missing_value_is_filled_from_the_duplicate():
    records = [
        _rec(employee_id="EMP1", email=None, full_name="A"),
        _rec(employee_id="EMP1", email="a@x.com", full_name="A", file="hr.xlsx"),
    ]
    result = deduplication.reconcile_group(records, [0, 1], {0: 1, 1: 2})
    assert result.merged_values["email"] == "a@x.com"
    assert not any(c.field_name == "email" for c in result.conflicts)


# -------------------------------------------------------------- validation
def test_validation_catches_missing_mandatory_fields():
    issues = validation.validate_record(
        {"employee_id": "EMP1", "full_name": "A B", "email": None, "status": "active"}
    )
    codes = {(i.field, i.code) for i in issues}
    assert ("email", "required_missing") in codes


def test_validation_rejects_bad_enum_and_email():
    issues = validation.validate_record(
        {
            "employee_id": "EMP1",
            "full_name": "A B",
            "email": "not-an-email",
            "status": "retired",
        }
    )
    codes = {i.code for i in issues}
    assert "invalid_email" in codes and "invalid_enum" in codes


def test_auto_repair_fixes_only_deterministic_problems():
    record = {
        "employee_id": "EMP1",
        "full_name": "A B",
        "email": " A.B@X.COM ",
        "status": "Active",
    }
    issues = validation.validate_record(record)
    repaired, applied = validation.attempt_repair(record, issues)
    assert repaired["email"] == "a.b@x.com"
    assert repaired["status"] == "active"
    assert {a["rule"] for a in applied} == {
        "repair_email_casing_whitespace",
        "repair_enum_casing",
    }
    assert validation.validate_record(repaired) == []


def test_auto_repair_gives_up_on_a_genuinely_missing_value():
    record = {"employee_id": "EMP1", "full_name": "A B", "email": None, "status": "active"}
    issues = validation.validate_record(record)
    repaired, applied = validation.attempt_repair(record, issues)
    assert applied == []
    assert repaired["email"] is None


def test_duplicate_primary_keys_are_detected():
    dupes = validation.check_unique_employee_ids(
        [{"employee_id": "EMP1"}, {"employee_id": "emp1 "}, {"employee_id": "EMP2"}]
    )
    assert list(dupes) == ["EMP1"]
