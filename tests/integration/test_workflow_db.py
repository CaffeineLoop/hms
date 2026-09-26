"""Stage 4 schema and PostgreSQL-enforced integrity; migration 0006 on hms_test only."""

import uuid
from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

T = datetime(2026, 1, 10, 9, tzinfo=UTC)
LATER = datetime(2026, 1, 10, 10, tzinfo=UTC)
STAGE4 = ("departments", "staff", "appointments", "admissions", "admission_transfers", "workflow_tasks")
STAFF_REFERENCES = [
    ("encounters", "attending_staff_id"), ("clinical_notes", "author_staff_id"),
    ("lab_orders", "ordered_by_staff_id"), ("lab_orders", "verified_by_staff_id"),
    ("lab_samples", "collected_by_staff_id"), ("lab_results", "entered_by_staff_id"),
    ("reports", "author_staff_id"), ("reports", "requested_by_staff_id"), ("reports", "verified_by_staff_id"),
    ("prescriptions", "prescriber_staff_id"),
]


def insert(connection, table: str, **values):
    columns = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    return connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params}) RETURNING id"), values).scalar_one()


def violation(test_engine, statement) -> str:
    with pytest.raises(IntegrityError) as exc:
        with test_engine.begin() as connection:
            statement(connection)
    return exc.value.orig.diag.constraint_name


@pytest.fixture
def world(test_engine, clean_patients):
    with test_engine.begin() as c:
        dept = insert(c, "departments", name="Ward", status="ACTIVE")
        staff = insert(c, "staff", employee_code="EMP-1", first_name="A", last_name="B", designation="NURSE",
                       department_id=dept, status="ACTIVE")
        p = insert(c, "patients", patient_number="PAT-900001", first_name="P", last_name="Q",
                   date_of_birth=date(1980, 1, 1), sex="MALE")
        q = insert(c, "patients", patient_number="PAT-900002", first_name="R", last_name="S",
                   date_of_birth=date(1980, 1, 1), sex="MALE")
        enc_p = insert(c, "encounters", patient_id=p, encounter_type="OPD", status="IN_PROGRESS", reason="x", start_at=T)
    return {"dept": dept, "staff": staff, "p": p, "q": q, "enc_p": enc_p}


def admission(w, **overrides):
    return {"patient_id": w["p"], "department_id": w["dept"], "admission_type": "ELECTIVE", "reason": "x",
            "status": "REQUESTED", "requested_by_staff_id": w["staff"], "requested_at": T, **overrides}


def appointment(w, **overrides):
    return {"patient_id": w["p"], "department_id": w["dept"], "reason": "x", "scheduled_start": T,
            "duration_minutes": 15, "status": "REQUESTED", **overrides}


# --- schema -----------------------------------------------------------------------------------


def test_stage4_foreign_keys_restrict_and_staff_columns_nullable(test_engine, migrated_database):
    inspector = inspect(test_engine)
    for table in STAGE4:
        for fk in inspector.get_foreign_keys(table):
            assert fk["options"].get("ondelete") == "RESTRICT", (table, fk["name"])
    for table, column in STAFF_REFERENCES:
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert columns[column]["nullable"] is True, (table, column)
        fks = {fk["name"]: fk for fk in inspector.get_foreign_keys(table)}
        fk = fks[f"fk_{table}_{column}_staff"]
        assert fk["referred_table"] == "staff" and fk["options"].get("ondelete") == "RESTRICT"


# --- constraints --------------------------------------------------------------------------------


def test_department_and_staff_uniqueness(test_engine, world):
    assert violation(test_engine, lambda c: insert(c, "departments", name="WARD", status="ACTIVE")) == "uq_departments_lower_name"
    staff = {"first_name": "C", "last_name": "D", "designation": "NURSE", "department_id": world["dept"], "status": "ACTIVE"}
    assert violation(test_engine, lambda c: insert(c, "staff", employee_code="EMP-1", **staff)) == "uq_staff_employee_code"
    assert violation(test_engine, lambda c: insert(c, "staff", employee_code="emp-2", **staff)) == "ck_staff_employee_code_format"
    assert violation(test_engine, lambda c: insert(c, "staff", employee_code="EMP-3", **{**staff, "status": "INACTIVE"})
                     ) == "ck_staff_deactivation_matches_status"
    assert violation(test_engine, lambda c: insert(c, "staff", employee_code="EMP-4", **{**staff, "designation": "WIZARD"})
                     ) == "ck_staff_designation_valid"


def test_one_open_admission_per_patient(test_engine, world):
    with test_engine.begin() as c:
        insert(c, "admissions", **admission(world))
        insert(c, "admissions", **admission(world, status="CANCELLED", cancelled_at=LATER, cancellation_reason="x"))
        insert(c, "admissions", **admission(world, patient_id=world["q"]))
    assert violation(test_engine, lambda c: insert(c, "admissions", **admission(world))) == "uq_admissions_one_open_per_patient"


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"status": "ADMITTED"}, "ck_admissions_admission_matches_status"),
    ({"status": "APPROVED"}, "ck_admissions_approval_matches_status"),
    ({"status": "CANCELLED"}, "ck_admissions_cancellation_matches_status"),
    ({"admission_type": "URGENT"}, "ck_admissions_admission_type_valid"),
    ({"discharge_disposition": "CURED"}, "ck_admissions_discharge_disposition_valid"),
])
def test_admission_checks(test_engine, world, overrides, constraint):
    assert violation(test_engine, lambda c: insert(c, "admissions", **admission(world, **overrides))) == constraint


def test_admission_encounter_must_be_same_patient(test_engine, world):
    values = admission(world, patient_id=world["q"], status="ADMITTED", encounter_id=world["enc_p"],
                       approved_at=T, approved_by_staff_id=world["staff"], admitted_at=T)
    assert violation(test_engine, lambda c: insert(c, "admissions", **values)) == "fk_admissions_encounter_id_encounters"


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"status": "IN_CONSULTATION"}, "ck_appointments_encounter_matches_status"),
    ({"status": "NO_SHOW"}, "ck_appointments_no_show_matches_status"),
    ({"duration_minutes": 1}, "ck_appointments_duration_valid"),
    ({"status": "BOOKED"}, "ck_appointments_status_valid"),
])
def test_appointment_checks(test_engine, world, overrides, constraint):
    assert violation(test_engine, lambda c: insert(c, "appointments", **appointment(world, **overrides))) == constraint


def test_transfer_must_change_location_and_belong_to_patient(test_engine, world):
    with test_engine.begin() as c:
        adm = insert(c, "admissions", **admission(world))
    base = {"patient_id": world["p"], "admission_id": adm, "from_department_id": world["dept"],
            "to_department_id": world["dept"], "reason": "x", "transferred_at": T}
    assert violation(test_engine, lambda c: insert(c, "admission_transfers", **base)) == "ck_admission_transfers_location_changes"
    assert violation(test_engine, lambda c: insert(c, "admission_transfers", **{**base, "patient_id": world["q"], "to_bed": "2"})
                     ) == "fk_admission_transfers_admission_id_admissions"


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"status": "ASSIGNED"}, "ck_workflow_tasks_assignment_matches_status"),
    ({"status": "COMPLETED", "assigned_staff_id": "STAFF", "assigned_at": T}, "ck_workflow_tasks_completion_matches_status"),
    ({"priority": "CRITICAL"}, "ck_workflow_tasks_priority_valid"),
    ({"workflow_type": "CLEANING"}, "ck_workflow_tasks_workflow_type_valid"),
])
def test_task_checks(test_engine, world, overrides, constraint):
    values = {"workflow_type": "OTHER", "title": "x", "priority": "NORMAL", "status": "OPEN", **overrides}
    if values.get("assigned_staff_id") == "STAFF":
        values["assigned_staff_id"] = world["staff"]
    assert violation(test_engine, lambda c: insert(c, "workflow_tasks", **values)) == constraint


def test_staff_and_departments_cannot_be_deleted_when_referenced(test_engine, world):
    assert violation(test_engine, lambda c: c.execute(text("DELETE FROM departments WHERE id = :i"), {"i": world["dept"]})
                     ) == "fk_staff_department_id_departments"
    with test_engine.begin() as c:
        c.execute(text("UPDATE encounters SET attending_staff_id = :s WHERE id = :e"),
                  {"s": world["staff"], "e": world["enc_p"]})
    assert violation(test_engine, lambda c: c.execute(text("DELETE FROM staff WHERE id = :i"), {"i": world["staff"]})
                     ) == "fk_encounters_attending_staff_id_staff"


# --- migration 0006 (hms_test only) ------------------------------------------------------------------


def test_migration_0006_downgrade_keeps_legacy_data_and_reupgrades(test_database_url, alembic_config, world, test_engine):
    """Downgrading removes Stage 4 tables/columns only; free-text names on existing records are untouched."""
    with test_engine.begin() as c:
        order = insert(c, "lab_orders", patient_id=world["p"], encounter_id=world["enc_p"], order_number="LAB-900001",
                       test_code="fbc", test_name="FBC", priority="ROUTINE", status="ORDERED",
                       ordered_by="Dr. Legacy Free-Text", ordered_at=T)
    engine = create_engine(test_database_url, poolclass=pool.NullPool)
    try:
        command.downgrade(alembic_config, "0005")
        inspector = inspect(engine)
        assert not set(inspector.get_table_names()) & set(STAGE4)
        for table, column in STAFF_REFERENCES:
            assert column not in {c["name"] for c in inspect(engine).get_columns(table)}
        with engine.connect() as connection:
            assert connection.execute(text("SELECT ordered_by FROM lab_orders WHERE id = :i"),
                                      {"i": order}).scalar_one() == "Dr. Legacy Free-Text"
        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            row = connection.execute(text("SELECT ordered_by, ordered_by_staff_id FROM lab_orders WHERE id = :i"),
                                     {"i": order}).one()
        assert tuple(row) == ("Dr. Legacy Free-Text", None)  # not back-filled
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
