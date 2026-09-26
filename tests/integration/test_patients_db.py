"""Patient table schema, constraints and repository behaviour, straight against PostgreSQL.

These tests bypass the API on purpose: they prove the database itself rejects bad
data even if a future code path skips the schema/service validation.
"""

import uuid
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.exc import IntegrityError

from app.models.patient import Patient, PatientStatus, format_patient_number
from app.repositories.patient_repository import PatientRepository

pytestmark = pytest.mark.integration

EXPECTED_CHECKS = {
    "ck_patients_patient_number_format",
    "ck_patients_first_name_not_blank",
    "ck_patients_last_name_not_blank",
    "ck_patients_date_of_birth_min",
    "ck_patients_sex_valid",
    "ck_patients_status_valid",
    "ck_patients_deactivation_consistent",
    "ck_patients_emergency_contact_complete",
}
EXPECTED_INDEXES = {
    "ix_patients_created_at",
    "ix_patients_date_of_birth",
    "ix_patients_email",
    "ix_patients_lower_name_dob",
    "ix_patients_phone",
    "ix_patients_status",
    "uq_patients_identity_phone",
    "uq_patients_identity_email",
}


def insert_sql(**overrides) -> tuple[str, dict]:
    values = {
        "patient_number": "PAT-900001",
        "first_name": "Amina",
        "last_name": "Okafor",
        "date_of_birth": date(1988, 4, 12),
        "sex": "FEMALE",
    }
    values.update(overrides)
    columns = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    return f"INSERT INTO patients ({columns}) VALUES ({params})", values


def assert_rejected(test_engine, *constraints: str, **overrides) -> None:
    """The insert must fail on one of `constraints` (PostgreSQL checks CHECKs in name order
    and reports only the first violation)."""
    sql, params = insert_sql(**overrides)
    with pytest.raises(IntegrityError) as exc:
        with test_engine.begin() as connection:
            connection.execute(text(sql), params)
    assert exc.value.orig.diag.constraint_name in constraints


# --- schema created by migration 0002 ----------------------------------------


def test_patients_table_structure(test_engine, migrated_database):
    inspector = inspect(test_engine)
    columns = {c["name"]: c for c in inspector.get_columns("patients")}
    required = {"id", "patient_number", "first_name", "last_name", "date_of_birth", "sex",
                "status", "created_at", "updated_at"}
    assert {name for name, c in columns.items() if not c["nullable"]} == required
    assert str(columns["id"]["type"]) == "UUID"
    pk = inspector.get_pk_constraint("patients")
    assert (pk["name"], pk["constrained_columns"]) == ("pk_patients", ["id"])
    assert [u["name"] for u in inspector.get_unique_constraints("patients")] == ["uq_patients_patient_number"]
    assert {c["name"] for c in inspector.get_check_constraints("patients")} == EXPECTED_CHECKS
    indexes = {i["name"] for i in inspector.get_indexes("patients") if not i.get("duplicates_constraint")}
    assert indexes == EXPECTED_INDEXES
    assert inspector.get_foreign_keys("patients") == []  # root entity: nothing referenced yet


def test_no_clinical_columns_on_patients(test_engine, migrated_database):
    """Patient identity is kept separate from future clinical records."""
    columns = {c["name"] for c in inspect(test_engine).get_columns("patients")}
    clinical = {"diagnosis", "allergies", "notes", "blood_type", "vitals", "condition", "medications"}
    assert not columns & clinical


def test_patient_number_sequence_is_owned_by_column(test_engine, migrated_database):
    with test_engine.connect() as connection:
        owner = connection.execute(text(
            "SELECT pg_get_serial_sequence('patients', 'patient_number')"
        )).scalar_one()
    assert owner == "public.patient_number_seq"


def test_migration_downgrade_removes_table_and_sequence(test_database_url, alembic_config):
    try:
        command.downgrade(alembic_config, "0001")
        engine = create_engine(test_database_url, poolclass=pool.NullPool)
        try:
            with engine.connect() as connection:
                assert connection.execute(text("SELECT to_regclass('public.patients')")).scalar_one() is None
                assert connection.execute(
                    text("SELECT to_regclass('public.patient_number_seq')")
                ).scalar_one() is None
        finally:
            engine.dispose()
    finally:
        command.upgrade(alembic_config, "head")


# --- constraints ---------------------------------------------------------------


@pytest.mark.usefixtures("clean_patients")
class TestConstraints:
    def test_valid_row_uses_server_defaults(self, test_engine):
        sql, params = insert_sql()
        with test_engine.begin() as connection:
            connection.execute(text(sql), params)
            row = connection.execute(text(
                "SELECT id, status, created_at, updated_at FROM patients WHERE patient_number = 'PAT-900001'"
            )).one()
        assert isinstance(row.id, uuid.UUID)
        assert row.status == "ACTIVE"
        assert row.created_at is not None and row.updated_at is not None

    def test_patient_number_is_unique(self, test_engine):
        sql, params = insert_sql()
        with test_engine.begin() as connection:
            connection.execute(text(sql), params)
        assert_rejected(test_engine, "uq_patients_patient_number", first_name="Other")

    def test_primary_key_is_unique(self, test_engine):
        patient_id = uuid.uuid4()
        sql, params = insert_sql(id=patient_id)
        with test_engine.begin() as connection:
            connection.execute(text(sql), params)
        assert_rejected(test_engine, "pk_patients", id=patient_id, patient_number="PAT-900002")

    @pytest.mark.parametrize("column", ["patient_number", "first_name", "last_name", "date_of_birth", "sex"])
    def test_required_columns_are_not_null(self, test_engine, column):
        sql, params = insert_sql(**{column: None})
        with pytest.raises(IntegrityError) as exc:
            with test_engine.begin() as connection:
                connection.execute(text(sql), params)
        assert exc.value.orig.diag.column_name == column

    @pytest.mark.parametrize("value", ["PAT-1", "PAT-00001", "pat-000001", "P-000001", "PAT-00000A"])
    def test_patient_number_format(self, test_engine, value):
        assert_rejected(test_engine, "ck_patients_patient_number_format", patient_number=value)

    def test_blank_names(self, test_engine):
        assert_rejected(test_engine, "ck_patients_first_name_not_blank", first_name="   ")
        assert_rejected(test_engine, "ck_patients_last_name_not_blank", last_name="")

    def test_date_of_birth_lower_bound(self, test_engine):
        assert_rejected(test_engine, "ck_patients_date_of_birth_min", date_of_birth=date(1899, 12, 31))

    def test_sex_values(self, test_engine):
        assert_rejected(test_engine, "ck_patients_sex_valid", sex="female")

    def test_status_values(self, test_engine):
        # An unknown status also violates deactivation_consistent, which PostgreSQL evaluates first.
        assert_rejected(
            test_engine, "ck_patients_status_valid", "ck_patients_deactivation_consistent", status="DELETED"
        )
        assert_rejected(
            test_engine, "ck_patients_status_valid", "ck_patients_deactivation_consistent",
            status="DELETED", deactivated_at=date(2026, 1, 1),
        )

    def test_inactive_requires_deactivated_at(self, test_engine):
        assert_rejected(test_engine, "ck_patients_deactivation_consistent", status="INACTIVE")

    def test_active_cannot_carry_deactivation_data(self, test_engine):
        assert_rejected(
            test_engine, "ck_patients_deactivation_consistent",
            status="ACTIVE", deactivation_reason="stale reason",
        )

    def test_emergency_contact_must_be_complete(self, test_engine):
        assert_rejected(test_engine, "ck_patients_emergency_contact_complete", emergency_contact_name="Ben")
        assert_rejected(test_engine, "ck_patients_emergency_contact_complete",
                        emergency_contact_phone="0712345678")
        assert_rejected(test_engine, "ck_patients_emergency_contact_complete",
                        emergency_contact_relationship="Brother")

    def test_column_lengths_enforced(self, test_engine):
        sql, params = insert_sql(first_name="x" * 101)
        with pytest.raises(Exception, match="value too long"):
            with test_engine.begin() as connection:
                connection.execute(text(sql), params)


# --- repository ------------------------------------------------------------------


def make_patient(repository: PatientRepository, **overrides) -> Patient:
    values = {
        "first_name": "Amina",
        "last_name": "Okafor",
        "date_of_birth": date(1988, 4, 12),
        "sex": "FEMALE",
        "patient_number": format_patient_number(repository.next_patient_number_value()),
    }
    values.update(overrides)
    return repository.add(Patient(**values))


def test_sequence_values_are_never_reused(db_session):
    repository = PatientRepository(db_session)
    first = repository.next_patient_number_value()
    db_session.rollback()  # sequences are non-transactional: the value stays consumed
    second = repository.next_patient_number_value()
    assert second > first


def test_repository_add_and_get(db_session):
    repository = PatientRepository(db_session)
    patient = make_patient(repository)
    db_session.commit()
    fetched = repository.get(patient.id)
    assert fetched is not None and fetched.patient_number == patient.patient_number
    assert fetched.status == PatientStatus.ACTIVE
    assert repository.get(uuid.uuid4()) is None


def test_repository_search_counts_before_pagination(db_session):
    repository = PatientRepository(db_session)
    for i in range(5):
        make_patient(repository, first_name=f"Name{i}")
    db_session.commit()
    items, total = repository.search(search="name", limit=2, offset=0)
    assert total == 5 and len(items) == 2


def test_repository_find_duplicates(db_session):
    repository = PatientRepository(db_session)
    original = make_patient(repository, phone="0712345678")
    db_session.commit()
    common = {"first_name": "AMINA", "last_name": "OKAFOR", "date_of_birth": date(1988, 4, 12)}
    assert repository.find_duplicates(**common, phone="0712345678", email=None) == [original]
    assert repository.find_duplicates(**common, phone="0799999999", email=None) == []
    assert repository.find_duplicates(**common, phone=None, email=None) == []
    assert repository.find_duplicates(**common, phone="0712345678", email=None, exclude_id=original.id) == []


def test_updated_at_changes_on_update(db_session):
    repository = PatientRepository(db_session)
    patient = make_patient(repository)
    db_session.commit()
    db_session.refresh(patient)
    before = patient.updated_at
    patient.city = "Kisumu"
    db_session.commit()
    db_session.refresh(patient)
    assert patient.updated_at > before
    assert patient.created_at <= before
