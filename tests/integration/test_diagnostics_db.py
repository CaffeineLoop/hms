"""Stage 3 schema and PostgreSQL-enforced integrity (bypasses the API on purpose)."""

import uuid
from datetime import UTC, date, datetime

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

T = datetime(2026, 1, 10, 9, 0, tzinfo=UTC)
LATER = datetime(2026, 1, 10, 10, 0, tzinfo=UTC)
STAGE3 = ("lab_orders", "lab_samples", "lab_results", "reports", "prescriptions", "prescription_items")
SEQUENCES = {"lab_order_number_seq": ("lab_orders", "order_number"),
             "lab_sample_accession_seq": ("lab_samples", "accession_number"),
             "prescription_number_seq": ("prescriptions", "prescription_number")}


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
    """Two patients, each with an encounter; patient A has one lab order and one prescription."""
    with test_engine.begin() as c:
        a = insert(c, "patients", patient_number="PAT-900001", first_name="A", last_name="A",
                   date_of_birth=date(1980, 1, 1), sex="FEMALE")
        b = insert(c, "patients", patient_number="PAT-900002", first_name="B", last_name="B",
                   date_of_birth=date(1980, 1, 1), sex="MALE")
        enc_a = insert(c, "encounters", patient_id=a, encounter_type="OPD", status="IN_PROGRESS", reason="x", start_at=T)
        enc_b = insert(c, "encounters", patient_id=b, encounter_type="OPD", status="IN_PROGRESS", reason="x", start_at=T)
        order_a = insert(c, "lab_orders", **lab_order(a, enc_a))
        rx_a = insert(c, "prescriptions", **prescription(a, enc_a))
    return {"a": a, "b": b, "enc_a": enc_a, "enc_b": enc_b, "order_a": order_a, "rx_a": rx_a}


def lab_order(patient, encounter, number=900001, **overrides):
    return {"patient_id": patient, "encounter_id": encounter, "order_number": f"LAB-{number:06d}",
            "test_code": "fbc", "test_name": "FBC", "priority": "ROUTINE", "status": "ORDERED",
            "ordered_by": "Dr", "ordered_at": T, **overrides}


def prescription(patient, encounter, number=900001, **overrides):
    return {"patient_id": patient, "encounter_id": encounter, "prescription_number": f"RX-{number:06d}",
            "prescriber_name": "Dr", "status": "DRAFT", "prescribed_at": T, **overrides}


def result(patient, order, **overrides):
    return {"patient_id": patient, "lab_order_id": order, "analyte_code": "hb", "analyte_name": "Hb",
            "value_numeric": 13.0, "unit": "g/dL", "resulted_at": LATER, "entered_by": "T", **overrides}


def item(rx, line=1, **overrides):
    return {"prescription_id": rx, "line_number": line, "medicine_name": "Amoxicillin", "dose_value": 500,
            "dose_unit": "mg", "route": "ORAL", "frequency": "TID", **overrides}


# --- schema -------------------------------------------------------------------------------


def test_stage3_tables_keys_and_timestamps(test_engine, migrated_database):
    inspector = inspect(test_engine)
    for table in STAGE3:
        assert inspector.get_pk_constraint(table)["constrained_columns"] == ["id"]
        for fk in inspector.get_foreign_keys(table):
            assert fk["options"].get("ondelete") == "RESTRICT", (table, fk["name"])
    fks = {fk["name"]: fk for t in STAGE3 for fk in inspector.get_foreign_keys(t)}
    for name in ("fk_lab_samples_lab_order_id_lab_orders", "fk_lab_results_lab_order_id_lab_orders",
                 "fk_reports_lab_order_id_lab_orders"):
        assert fks[name]["constrained_columns"] == ["lab_order_id", "patient_id"]
        assert fks[name]["referred_columns"] == ["id", "patient_id"]
    for name in ("fk_lab_orders_encounter_id_encounters", "fk_prescriptions_encounter_id_encounters",
                 "fk_reports_encounter_id_encounters"):
        assert fks[name]["constrained_columns"] == ["encounter_id", "patient_id"]
    nullable = {t: {c["name"]: c["nullable"] for c in inspector.get_columns(t)} for t in STAGE3}
    assert nullable["lab_orders"]["encounter_id"] is False
    assert nullable["prescriptions"]["encounter_id"] is False
    assert nullable["reports"]["encounter_id"] is True and nullable["reports"]["lab_order_id"] is True
    with test_engine.connect() as connection:
        naive = connection.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type = 'timestamp without time zone'")).all()
        owners = {name: connection.execute(text("SELECT pg_get_serial_sequence(:t, :c)"),
                                           {"t": t, "c": c}).scalar_one() for name, (t, c) in SEQUENCES.items()}
    assert naive == []
    assert owners == {name: f"public.{name}" for name in SEQUENCES}


# --- relationships -----------------------------------------------------------------------------


def test_lab_children_cannot_cross_patients(test_engine, world):
    assert violation(test_engine, lambda c: insert(c, "lab_samples", patient_id=world["b"], lab_order_id=world["order_a"],
                     accession_number="SMP-900001", specimen_type="BLOOD", collected_at=T, collected_by="N")
                     ) == "fk_lab_samples_lab_order_id_lab_orders"
    assert violation(test_engine, lambda c: insert(c, "lab_results", **result(world["b"], world["order_a"]))
                     ) == "fk_lab_results_lab_order_id_lab_orders"
    assert violation(test_engine, lambda c: insert(c, "reports", patient_id=world["b"], lab_order_id=world["order_a"],
                     report_type="LABORATORY", title="x", status="DRAFT", effective_at=T, author_name="a")
                     ) == "fk_reports_lab_order_id_lab_orders"


def test_orders_and_prescriptions_cannot_use_other_patients_encounter(test_engine, world):
    assert violation(test_engine, lambda c: insert(c, "lab_orders", **lab_order(world["b"], world["enc_a"], 900002))
                     ) == "fk_lab_orders_encounter_id_encounters"
    assert violation(test_engine, lambda c: insert(c, "prescriptions", **prescription(world["b"], world["enc_a"], 900002))
                     ) == "fk_prescriptions_encounter_id_encounters"


def test_restrict_deletes(test_engine, world):
    with test_engine.begin() as c:
        insert(c, "prescription_items", **item(world["rx_a"]))
    assert violation(test_engine, lambda c: c.execute(text("DELETE FROM prescriptions WHERE id = :i"), {"i": world["rx_a"]})
                     ) == "fk_prescription_items_prescription_id_prescriptions"
    assert violation(test_engine, lambda c: c.execute(text("DELETE FROM encounters WHERE id = :i"), {"i": world["enc_a"]})
                     ) in {"fk_lab_orders_encounter_id_encounters", "fk_prescriptions_encounter_id_encounters"}


# --- lifecycle / value constraints ------------------------------------------------------------------


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"status": "DONE"}, "ck_lab_orders_status_valid"),
    ({"priority": "ASAP"}, "ck_lab_orders_priority_valid"),
    ({"order_number": "LAB-12"}, "ck_lab_orders_order_number_format"),
    ({"test_code": "Full Blood"}, "ck_lab_orders_test_code_format"),
    ({"status": "VERIFIED"}, "ck_lab_orders_verification_matches_status"),
    ({"verified_by": "x", "verified_at": LATER}, "ck_lab_orders_verification_matches_status"),
    ({"status": "RELEASED", "verified_by": "x", "verified_at": LATER}, "ck_lab_orders_release_matches_status"),
    ({"status": "CANCELLED"}, "ck_lab_orders_cancellation_matches_status"),
    ({"status": "PROCESSING", "processing_started_at": datetime(2026, 1, 1, tzinfo=UTC)}, "ck_lab_orders_timestamps_ordered"),
])
def test_lab_order_checks(test_engine, world, overrides, constraint):
    values = lab_order(world["a"], world["enc_a"], 900003, **overrides)
    assert violation(test_engine, lambda c: insert(c, "lab_orders", **values)) == constraint


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"value_numeric": None}, "ck_lab_results_exactly_one_value"),
    ({"value_text": "x"}, "ck_lab_results_exactly_one_value"),
    ({"reference_low": 5, "reference_high": 1}, "ck_lab_results_reference_range_ordered"),
    ({"value_numeric": None, "value_text": "pos", "unit": None, "reference_low": 1},
     "ck_lab_results_numeric_range_only_for_numeric"),
    ({"interpretation": "WEIRD"}, "ck_lab_results_interpretation_valid"),
])
def test_lab_result_checks(test_engine, world, overrides, constraint):
    values = result(world["a"], world["order_a"], **overrides)
    assert violation(test_engine, lambda c: insert(c, "lab_results", **values)) == constraint


def test_one_result_per_analyte(test_engine, world):
    with test_engine.begin() as c:
        insert(c, "lab_results", **result(world["a"], world["order_a"]))
    assert violation(test_engine, lambda c: insert(c, "lab_results", **result(world["a"], world["order_a"]))
                     ) == "uq_lab_results_lab_order_id_analyte_code"


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"status": "VERIFIED", "verified_by": "v", "verified_at": T}, "ck_reports_content_required_after_draft"),
    ({"report_type": "IMAGING", "lab_order_id": "ORDER"}, "ck_reports_lab_order_only_for_laboratory"),
    ({"status": "RELEASED", "content": "x", "released_at": LATER}, "ck_reports_verification_matches_status"),
    ({"status": "VERIFIED", "content": "x", "verified_by": "v", "verified_at": T, "released_at": LATER},
     "ck_reports_release_matches_status"),
    ({"report_type": "XRAY"}, "ck_reports_report_type_valid"),
])
def test_report_checks(test_engine, world, overrides, constraint):
    values = {"patient_id": world["a"], "report_type": "LABORATORY", "title": "x", "status": "DRAFT",
              "effective_at": T, "author_name": "a", **overrides}
    if values.get("lab_order_id") == "ORDER":
        values["lab_order_id"] = world["order_a"]
    assert violation(test_engine, lambda c: insert(c, "reports", **values)) == constraint


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"status": "ACTIVE"}, "ck_prescriptions_activation_matches_status"),
    ({"activated_at": LATER}, "ck_prescriptions_activation_matches_status"),
    ({"status": "COMPLETED", "activated_at": LATER}, "ck_prescriptions_completion_matches_status"),
    ({"status": "ACTIVE", "activated_at": datetime(2025, 1, 1, tzinfo=UTC)}, "ck_prescriptions_timestamps_ordered"),
    ({"prescription_number": "RX-1"}, "ck_prescriptions_prescription_number_format"),
])
def test_prescription_checks(test_engine, world, overrides, constraint):
    values = prescription(world["a"], world["enc_a"], 900005, **overrides)
    assert violation(test_engine, lambda c: insert(c, "prescriptions", **values)) == constraint


@pytest.mark.parametrize(("overrides", "constraint"), [
    ({"dose_value": 0}, "ck_prescription_items_dose_positive"),
    ({"route": "MOUTH"}, "ck_prescription_items_route_valid"),
    ({"frequency": "THRICE"}, "ck_prescription_items_frequency_valid"),
    ({"duration_value": 7}, "ck_prescription_items_duration_valid"),
    ({"duration_value": 0, "duration_unit": "DAYS"}, "ck_prescription_items_duration_valid"),
    ({"quantity_unit": "tab"}, "ck_prescription_items_quantity_valid"),
    ({"line_number": 0}, "ck_prescription_items_line_number_positive"),
])
def test_prescription_item_checks(test_engine, world, overrides, constraint):
    values = item(world["rx_a"], **overrides)
    assert violation(test_engine, lambda c: insert(c, "prescription_items", **values)) == constraint


def test_unique_line_numbers(test_engine, world):
    with test_engine.begin() as c:
        insert(c, "prescription_items", **item(world["rx_a"]))
    assert violation(test_engine, lambda c: insert(c, "prescription_items", **item(world["rx_a"]))
                     ) == "uq_prescription_items_prescription_id_line_number"


# --- migration 0005 downgrade / upgrade -------------------------------------------------------------


def test_migration_0005_downgrade_removes_only_stage3(test_database_url, alembic_config, world):
    engine = create_engine(test_database_url, poolclass=pool.NullPool)
    try:
        command.downgrade(alembic_config, "0004")
        tables = set(inspect(engine).get_table_names())
        assert not tables & set(STAGE3)
        assert {"patients", "encounters"} <= tables
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM encounters")).scalar_one() == 2
            for name in SEQUENCES:
                assert connection.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar_one() is None
        command.upgrade(alembic_config, "head")
        assert set(STAGE3) <= set(inspect(engine).get_table_names())
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
