"""Stage 2 schema, PostgreSQL-enforced integrity, and the Stage 2 pre-flight fixes."""

import uuid
from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

T = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
CLINICAL = ("encounters", "observations", "conditions", "allergies", "clinical_notes")


def insert(connection, table: str, **values):
    columns = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    return connection.execute(text(f"INSERT INTO {table} ({columns}) VALUES ({params}) RETURNING id"), values).scalar_one()


def new_patient(connection, number: int, **overrides) -> uuid.UUID:
    values = {"patient_number": f"PAT-{number:06d}", "first_name": "Amina", "last_name": "Okafor",
              "date_of_birth": date(1980, 1, 1), "sex": "FEMALE", **overrides}
    return insert(connection, "patients", **values)


def new_encounter(connection, patient_id, **overrides) -> uuid.UUID:
    values = {"patient_id": patient_id, "encounter_type": "OPD", "status": "IN_PROGRESS",
              "reason": "Cough", "start_at": T, **overrides}
    return insert(connection, "encounters", **values)


def violation(test_engine, statement) -> str:
    """Run `statement(connection)` and return the violated constraint name."""
    with pytest.raises(IntegrityError) as exc:
        with test_engine.begin() as connection:
            statement(connection)
    return exc.value.orig.diag.constraint_name


@pytest.fixture
def two_patients(test_engine, clean_patients):
    with test_engine.begin() as connection:
        a = new_patient(connection, 900001)
        b = new_patient(connection, 900002, first_name="Brian")
        encounter_a = new_encounter(connection, a)
    return a, b, encounter_a


# --- schema --------------------------------------------------------------------------


def test_clinical_tables_and_foreign_keys(test_engine, migrated_database):
    inspector = inspect(test_engine)
    for table in CLINICAL:
        fks = {fk["name"]: fk for fk in inspector.get_foreign_keys(table)}
        patient_fk = fks[f"fk_{table}_patient_id_patients"]
        assert (patient_fk["referred_table"], patient_fk["constrained_columns"]) == ("patients", ["patient_id"])
        assert patient_fk["options"].get("ondelete") == "RESTRICT"
        if table != "encounters":
            encounter_fk = fks[f"fk_{table}_encounter_id_encounters"]
            assert encounter_fk["constrained_columns"] == ["encounter_id", "patient_id"]
            assert encounter_fk["referred_columns"] == ["id", "patient_id"]
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert str(columns["id"]["type"]) == "UUID" and not columns["patient_id"]["nullable"]
        for timestamp in ("created_at", "updated_at"):
            assert columns[timestamp]["type"].timezone is True
        if table == "clinical_notes":
            assert columns["encounter_id"]["nullable"] is False  # a note always belongs to an encounter


def test_every_clinical_timestamp_is_timestamptz(test_engine, migrated_database):
    with test_engine.connect() as connection:
        naive = connection.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'"
        )).all()
    assert naive == []


def test_patient_table_has_no_clinical_columns(test_engine, migrated_database):
    columns = {c["name"] for c in inspect(test_engine).get_columns("patients")}
    assert not columns & {"encounter_id", "value_numeric", "substance", "note_type", "reason", "code"}


# --- relationships -----------------------------------------------------------------------


def test_record_cannot_reference_another_patients_encounter(test_engine, two_patients):
    a, b, encounter_a = two_patients
    for table, extra in [
        ("observations", {"code": "heart_rate", "display": "HR", "value_numeric": 70, "unit": "/min", "effective_at": T}),
        ("conditions", {"name": "Asthma", "status": "ACTIVE", "recorded_at": T}),
        ("allergies", {"substance": "Latex", "status": "ACTIVE", "recorded_at": T}),
        ("clinical_notes", {"note_type": "OTHER", "author_name": "A", "content": "x", "authored_at": T}),
    ]:
        name = violation(test_engine, lambda c: insert(c, table, patient_id=b, encounter_id=encounter_a, **extra))
        assert name == f"fk_{table}_encounter_id_encounters"
        with test_engine.begin() as connection:  # same record for the right patient is fine
            insert(connection, table, patient_id=a, encounter_id=encounter_a, **extra)


def test_unknown_patient_rejected(test_engine, clean_patients):
    name = violation(test_engine, lambda c: new_encounter(c, uuid.uuid4()))
    assert name == "fk_encounters_patient_id_patients"


def test_patients_with_clinical_records_cannot_be_deleted(test_engine, two_patients):
    a, _, _ = two_patients
    name = violation(test_engine, lambda c: c.execute(text("DELETE FROM patients WHERE id = :id"), {"id": a}))
    assert name == "fk_encounters_patient_id_patients"


def test_encounter_with_records_cannot_be_deleted(test_engine, two_patients):
    a, _, encounter_a = two_patients
    with test_engine.begin() as connection:
        insert(connection, "clinical_notes", patient_id=a, encounter_id=encounter_a, note_type="OTHER",
               author_name="A", content="x", authored_at=T)
    name = violation(test_engine, lambda c: c.execute(text("DELETE FROM encounters WHERE id = :id"), {"id": encounter_a}))
    assert name == "fk_clinical_notes_encounter_id_encounters"


# --- CHECK constraints -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"encounter_type": "ICU"}, "ck_encounters_encounter_type_valid"),
        ({"status": "DONE"}, "ck_encounters_status_valid"),
        ({"reason": "  "}, "ck_encounters_reason_not_blank"),
        ({"status": "FINISHED", "end_at": datetime(2026, 1, 10, 8, tzinfo=UTC)}, "ck_encounters_end_after_start"),
        ({"status": "FINISHED"}, "ck_encounters_end_matches_status"),
        ({"end_at": datetime(2026, 1, 10, 10, tzinfo=UTC)}, "ck_encounters_end_matches_status"),
        ({"status": "CANCELLED"}, "ck_encounters_cancellation_reason_matches_status"),
        ({"cancellation_reason": "x"}, "ck_encounters_cancellation_reason_matches_status"),
    ],
)
def test_encounter_checks(test_engine, two_patients, overrides, constraint):
    a, _, _ = two_patients
    assert violation(test_engine, lambda c: new_encounter(c, a, **overrides)) == constraint


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"code": "Heart Rate"}, "ck_observations_code_format"),
        ({"value_numeric": None}, "ck_observations_exactly_one_value"),
        ({"value_text": "fast"}, "ck_observations_exactly_one_value"),
        ({"value_numeric": None, "value_text": "fast"}, "ck_observations_unit_only_for_numeric"),
        ({"code_system": "http://loinc.org"}, "ck_observations_coding_complete"),
    ],
)
def test_observation_checks(test_engine, two_patients, overrides, constraint):
    a, _, _ = two_patients
    values = {"patient_id": a, "code": "heart_rate", "display": "HR", "value_numeric": 70, "unit": "/min",
              "effective_at": T, **overrides}
    assert violation(test_engine, lambda c: insert(c, "observations", **values)) == constraint


def test_condition_allergy_note_checks(test_engine, two_patients):
    a, _, encounter_a = two_patients
    cond = {"patient_id": a, "name": "Asthma", "status": "ACTIVE", "recorded_at": T}
    assert violation(test_engine, lambda c: insert(c, "conditions", **{**cond, "status": "CURED"})) == "ck_conditions_status_valid"
    assert violation(test_engine, lambda c: insert(c, "conditions", **{
        **cond, "onset_at": T, "resolved_at": datetime(2025, 1, 1, tzinfo=UTC)})) == "ck_conditions_resolved_after_onset"
    allergy = {"patient_id": a, "substance": "Latex", "status": "ACTIVE", "recorded_at": T}
    assert violation(test_engine, lambda c: insert(c, "allergies", **{**allergy, "severity": "FATAL"})) == "ck_allergies_severity_valid"
    assert violation(test_engine, lambda c: insert(c, "allergies", **{**allergy, "category": "DRUG"})) == "ck_allergies_category_valid"
    note = {"patient_id": a, "encounter_id": encounter_a, "note_type": "OTHER", "author_name": "A",
            "content": "x", "authored_at": T}
    assert violation(test_engine, lambda c: insert(c, "clinical_notes", **{**note, "note_type": "AI"})) == "ck_clinical_notes_note_type_valid"
    assert violation(test_engine, lambda c: insert(c, "clinical_notes", **{**note, "content": " "})) == "ck_clinical_notes_content_not_blank"
    with pytest.raises(IntegrityError, match="encounter_id"):
        with test_engine.begin() as connection:
            insert(connection, "clinical_notes", **{**note, "encounter_id": None})


def test_one_active_allergy_per_substance(test_engine, two_patients):
    a, b, _ = two_patients
    allergy = {"substance": "Peanut", "status": "ACTIVE", "recorded_at": T}
    with test_engine.begin() as connection:
        insert(connection, "allergies", patient_id=a, **allergy)
        insert(connection, "allergies", patient_id=a, **{**allergy, "status": "INACTIVE"})  # history is fine
        insert(connection, "allergies", patient_id=b, **allergy)  # other patient is fine
    name = violation(test_engine, lambda c: insert(c, "allergies", patient_id=a, **{**allergy, "substance": "PEANUT"}))
    assert name == "uq_allergies_active_substance"


# --- pre-flight: database-enforced patient uniqueness ---------------------------------------------


def test_patient_identity_unique_by_phone(test_engine, clean_patients):
    with test_engine.begin() as connection:
        new_patient(connection, 900001, phone="+254712345678")
        new_patient(connection, 900002, phone="+254799999999")          # different phone: allowed
        new_patient(connection, 900003, date_of_birth=date(1981, 1, 1), phone="+254712345678")  # other DOB
        new_patient(connection, 900004)                                   # no contact: not constrained
        new_patient(connection, 900005)
    name = violation(test_engine, lambda c: new_patient(
        c, 900006, first_name="AMINA", last_name="okafor", phone="+254712345678"))
    assert name == "uq_patients_identity_phone"


def test_patient_identity_unique_by_email(test_engine, clean_patients):
    with test_engine.begin() as connection:
        new_patient(connection, 900001, email="amina@example.org")
    name = violation(test_engine, lambda c: new_patient(c, 900002, email="amina@example.org"))
    assert name == "uq_patients_identity_email"


def test_database_backstop_returns_friendly_409(client, clean_patients, monkeypatch, patient_payload):
    """Simulates two concurrent requests: the service pre-check sees nothing, PostgreSQL still refuses."""
    from app.repositories.patient_repository import PatientRepository

    body = patient_payload(phone="0712345678")
    assert client.post("/api/patients", json=body).status_code == 201
    monkeypatch.setattr(PatientRepository, "find_duplicates", lambda self, **kwargs: [])
    response = client.post("/api/patients", json=body)
    assert response.status_code == 409
    assert response.json() == {"detail": "A patient with the same name, date of birth and phone already exists."}


def test_allergy_backstop_returns_friendly_409(client, clean_patients, monkeypatch, patient_payload):
    from app.repositories.clinical_repository import AllergyRepository

    patient = client.post("/api/patients", json=patient_payload()).json()
    assert client.post(f"/api/patients/{patient['id']}/allergies", json={"substance": "Latex"}).status_code == 201
    monkeypatch.setattr(AllergyRepository, "active_for_substance", lambda self, *a, **k: None)
    response = client.post(f"/api/patients/{patient['id']}/allergies", json={"substance": "latex"})
    assert response.status_code == 409
    assert response.json() == {"detail": "The patient already has an active allergy to this substance."}


# --- pre-flight: time handling -------------------------------------------------------------------


def test_sessions_run_in_utc(test_engine):
    with test_engine.connect() as connection:
        assert connection.execute(text("SHOW TimeZone")).scalar_one() == "UTC"
        now = connection.execute(text("SELECT now()")).scalar_one()
    assert now.utcoffset().total_seconds() == 0


def test_api_timestamps_are_utc(client, clean_patients, patient_payload):
    patient = client.post("/api/patients", json=patient_payload()).json()
    assert patient["created_at"].endswith("Z") and patient["updated_at"].endswith("Z")
    obs = client.post(f"/api/patients/{patient['id']}/observations", json={
        "code": "heart_rate", "value_numeric": 70, "unit": "/min", "effective_at": "2026-01-10T14:30:00+05:30"}).json()
    assert obs["effective_at"] == "2026-01-10T09:00:00Z"


# --- pre-flight: migration 0003 normalizes stored phones ---------------------------------------


def test_migration_0003_normalizes_international_prefix(test_database_url, alembic_config, clean_patients):
    engine = create_engine(test_database_url, poolclass=pool.NullPool)
    try:
        command.downgrade(alembic_config, "0002")
        with engine.begin() as connection:
            new_patient(connection, 900001, phone="00254712345678", emergency_contact_name="Ben",
                        emergency_contact_phone="0044207946095")
        command.upgrade(alembic_config, "0003")
        with engine.connect() as connection:
            row = connection.execute(text("SELECT phone, emergency_contact_phone FROM patients")).one()
        assert tuple(row) == ("+254712345678", "+44207946095")
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()


def test_migration_0004_downgrade_keeps_patients(test_database_url, alembic_config, clean_patients):
    engine = create_engine(test_database_url, poolclass=pool.NullPool)
    try:
        with engine.begin() as connection:
            new_patient(connection, 900001)
        command.downgrade(alembic_config, "0003")
        tables = set(inspect(engine).get_table_names())
        assert not tables & set(CLINICAL)
        assert "patients" in tables
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM patients")).scalar_one() == 1
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
