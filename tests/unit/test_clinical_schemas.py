"""Stage 2 request validation, observation catalog and status-transition rules (no database)."""

import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.errors import ConflictError
from app.models.allergy import ALLERGY_TRANSITIONS, AllergyStatus
from app.models.condition import CONDITION_TRANSITIONS, ConditionStatus
from app.models.encounter import ENCOUNTER_TRANSITIONS, EncounterStatus
from app.schemas.clinical import (
    AllergyCreate,
    AllergyUpdate,
    ClinicalNoteCreate,
    ConditionCreate,
    ConditionUpdate,
    EncounterCancel,
    EncounterCreate,
    EncounterFinish,
    ObservationCreate,
)
from app.schemas.timeline import TimelineParams
from app.services.clinical_common import ensure_transition
from app.services.observation_catalog import CATALOG, LOINC

PAST = "2026-01-10T09:00:00Z"
LATER = "2026-01-10T11:30:00+02:00"  # 09:30Z


def future(minutes: int = 60) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


# --- timestamps (shared rules) -------------------------------------------------


@pytest.mark.parametrize("value", ["2026-01-10T09:00:00", "2026-01-10 09:00", "2026-01-10"])
def test_naive_or_date_only_timestamps_rejected(value):
    with pytest.raises(ValidationError):
        ObservationCreate(code="heart_rate", value_numeric=80, unit="/min", effective_at=value)


def test_timestamps_are_normalized_to_utc():
    obs = ObservationCreate(code="heart_rate", value_numeric=80, unit="/min", effective_at=LATER)
    assert obs.effective_at == datetime(2026, 1, 10, 9, 30, tzinfo=UTC)
    assert obs.effective_at.utcoffset() == timedelta(0)


def test_future_timestamp_rejected():
    with pytest.raises(ValidationError, match="future"):
        ObservationCreate(code="heart_rate", value_numeric=80, unit="/min", effective_at=future())


def test_small_clock_skew_tolerated():
    ObservationCreate(code="heart_rate", value_numeric=80, unit="/min", effective_at=future(minutes=2))


def test_timestamp_before_1900_rejected():
    with pytest.raises(ValidationError, match="1900"):
        ObservationCreate(code="heart_rate", value_numeric=80, unit="/min", effective_at="1899-12-31T23:00:00Z")


# --- encounters ------------------------------------------------------------------


def test_encounter_defaults_to_in_progress():
    encounter = EncounterCreate(encounter_type="OPD", reason="Cough")
    assert encounter.status == EncounterStatus.IN_PROGRESS and encounter.start_at is None


@pytest.mark.parametrize("encounter_type", ["OPD", "EMERGENCY", "INPATIENT", "FOLLOW_UP"])
def test_encounter_types(encounter_type):
    assert EncounterCreate(encounter_type=encounter_type, reason="x").encounter_type == encounter_type


@pytest.mark.parametrize(
    "overrides",
    [
        {"encounter_type": "ICU"},
        {"reason": "  "},
        {"status": "CANCELLED"},  # cannot be created cancelled
        {"status": "FINISHED", "start_at": PAST},  # missing end_at
        {"status": "PLANNED"},  # missing start_at
        {"start_at": PAST, "end_at": "2026-01-10T10:00:00Z"},  # end_at on an IN_PROGRESS encounter
        {"status": "FINISHED", "start_at": PAST, "end_at": "2026-01-10T08:00:00Z"},  # end before start
        {"start_at": None, "status": "FINISHED", "end_at": PAST},
        {"start_at": "2026-01-10T09:00:00"},  # naive
        {"unknown": 1},
    ],
)
def test_invalid_encounter_create(overrides):
    with pytest.raises(ValidationError):
        EncounterCreate(**{"encounter_type": "OPD", "reason": "Cough", **overrides})


def test_only_planned_encounters_may_start_in_the_future():
    assert EncounterCreate(encounter_type="OPD", reason="Review", status="PLANNED", start_at=future(24 * 60))
    with pytest.raises(ValidationError, match="PLANNED"):
        EncounterCreate(encounter_type="OPD", reason="Now", start_at=future())


def test_historical_finished_encounter():
    e = EncounterCreate(
        encounter_type="INPATIENT", reason="Pneumonia", status="FINISHED",
        start_at="2025-05-01T08:00:00Z", end_at="2025-05-04T12:00:00Z",
    )
    assert e.end_at - e.start_at == timedelta(days=3, hours=4)


def test_finish_and_cancel_bodies():
    assert EncounterFinish().end_at is None
    with pytest.raises(ValidationError):
        EncounterFinish(end_at=future())
    with pytest.raises(ValidationError):
        EncounterCancel(reason=" ")


# --- observations -------------------------------------------------------------------


def obs(**overrides):
    return {"code": "heart_rate", "value_numeric": 72, "unit": "/min", "effective_at": PAST, **overrides}


def test_catalog_observation_gets_display_and_loinc():
    o = ObservationCreate(**obs())
    assert (o.display, o.code_system, o.system_code) == ("Heart rate", LOINC, "8867-4")


@pytest.mark.parametrize(
    ("code", "value", "unit"),
    [
        ("body_temperature", 37.2, "Cel"),
        ("body_temperature", 99.1, "[degF]"),
        ("heart_rate", 72, "/min"),
        ("respiratory_rate", 16, "/min"),
        ("oxygen_saturation", 97, "%"),
        ("systolic_blood_pressure", 120, "mm[Hg]"),
        ("diastolic_blood_pressure", 80, "mm[Hg]"),
        ("body_weight", 70.5, "kg"),
        ("body_height", 172, "cm"),
        ("blood_glucose", 95, "mg/dL"),
        ("blood_glucose", 5.4, "mmol/L"),
    ],
)
def test_vital_signs_accepted(code, value, unit):
    assert ObservationCreate(**obs(code=code, value_numeric=value, unit=unit)).code == code


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"unit": "bpm"}, "unit for heart_rate must be one of"),
        ({"unit": None}, "unit for heart_rate"),
        ({"value_numeric": 400}, "outside the plausible range"),
        ({"value_numeric": -1}, "outside the plausible range"),
        ({"code": "oxygen_saturation", "value_numeric": 101, "unit": "%"}, "plausible range"),
        ({"code": "body_temperature", "value_numeric": 98.6, "unit": "Cel"}, "plausible range"),  # °F sent as °C
        ({"value_numeric": None, "value_text": "fast", "unit": None}, "requires value_numeric"),
        ({"value_numeric": None}, "exactly one of"),
        ({"value_text": "72"}, "exactly one of"),
        ({"value_numeric": math.inf}, "finite"),
        ({"value_numeric": math.nan}, "finite"),
        ({"code": "Heart Rate"}, "string_pattern_mismatch|pattern"),
        ({"code_system": "http://loinc.org"}, "given together"),
    ],
)
def test_invalid_observations(overrides, message):
    with pytest.raises(ValidationError, match=message):
        ObservationCreate(**obs(**overrides))


def test_code_is_lowercased():
    assert ObservationCreate(**obs(code="HEART_RATE")).code == "heart_rate"


def test_custom_observation_requires_display():
    with pytest.raises(ValidationError, match="display is required"):
        ObservationCreate(code="pain_score", value_numeric=4, effective_at=PAST)
    o = ObservationCreate(code="pain_score", display="Pain severity (0-10)", value_numeric=4, effective_at=PAST)
    assert o.unit is None and o.code_system is None


def test_text_observation_cannot_have_unit():
    with pytest.raises(ValidationError, match="unit is only allowed"):
        ObservationCreate(code="smoking_status", display="Smoking status", value_text="Never", unit="x",
                          effective_at=PAST)


def test_catalog_has_the_required_vitals():
    required = {"body_temperature", "heart_rate", "systolic_blood_pressure", "diastolic_blood_pressure",
                "respiratory_rate", "oxygen_saturation", "body_weight", "blood_glucose"}
    assert required <= set(CATALOG)


# --- conditions / allergies / notes ------------------------------------------------


def test_condition_defaults():
    c = ConditionCreate(name="Hypertension")
    assert c.status == ConditionStatus.ACTIVE and c.recorded_at is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"status": "CURED"},
        {"code": "38341003"},  # code without code_system
        {"onset_at": "2026-01-10T00:00:00Z", "resolved_at": "2026-01-01T00:00:00Z", "status": "RESOLVED"},
        {"resolved_at": PAST},  # resolved_at on an ACTIVE condition
        {"recorded_at": future()},
    ],
)
def test_invalid_condition(overrides):
    with pytest.raises(ValidationError):
        ConditionCreate(**{"name": "Hypertension", **overrides})


def test_condition_update_rules():
    with pytest.raises(ValidationError, match="at least one field"):
        ConditionUpdate()
    with pytest.raises(ValidationError, match="status cannot be null"):
        ConditionUpdate(status=None)
    with pytest.raises(ValidationError):
        ConditionUpdate(name="renamed")  # clinical facts are not rewritten


@pytest.mark.parametrize(
    "overrides",
    [{"substance": " "}, {"severity": "FATAL"}, {"category": "DRUG"}, {"status": "REFUTED"},
     {"code_system": "http://www.nlm.nih.gov/research/umls/rxnorm"}],
)
def test_invalid_allergy(overrides):
    with pytest.raises(ValidationError):
        AllergyCreate(**{"substance": "Penicillin", **overrides})


def test_allergy_update_requires_a_field():
    with pytest.raises(ValidationError):
        AllergyUpdate()
    with pytest.raises(ValidationError):
        AllergyUpdate(substance="Other")


@pytest.mark.parametrize(
    "overrides",
    [{"encounter_id": None}, {"encounter_id": "not-a-uuid"}, {"note_type": "AI_SUMMARY"},
     {"content": "   "}, {"author_name": ""}, {"authored_at": future()}],
)
def test_invalid_clinical_note(overrides):
    base = {"encounter_id": str(uuid.uuid4()), "note_type": "PROGRESS", "author_name": "Dr. A", "content": "Seen."}
    with pytest.raises(ValidationError):
        ClinicalNoteCreate(**{**base, **overrides})


# --- transitions ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("PLANNED", EncounterStatus.IN_PROGRESS, True),
        ("PLANNED", EncounterStatus.CANCELLED, True),
        ("PLANNED", EncounterStatus.FINISHED, False),
        ("IN_PROGRESS", EncounterStatus.FINISHED, True),
        ("IN_PROGRESS", EncounterStatus.CANCELLED, True),
        ("IN_PROGRESS", EncounterStatus.PLANNED, False),
        ("FINISHED", EncounterStatus.IN_PROGRESS, False),
        ("FINISHED", EncounterStatus.CANCELLED, False),
        ("CANCELLED", EncounterStatus.IN_PROGRESS, False),
        ("FINISHED", EncounterStatus.FINISHED, False),
    ],
)
def test_encounter_transitions(current, target, allowed):
    if allowed:
        ensure_transition("Encounter", current, target, ENCOUNTER_TRANSITIONS)
    else:
        with pytest.raises(ConflictError):
            ensure_transition("Encounter", current, target, ENCOUNTER_TRANSITIONS)


def test_terminal_encounter_states():
    assert ENCOUNTER_TRANSITIONS[EncounterStatus.FINISHED] == frozenset()
    assert ENCOUNTER_TRANSITIONS[EncounterStatus.CANCELLED] == frozenset()


def test_condition_and_allergy_transition_tables_cover_every_status():
    assert set(CONDITION_TRANSITIONS) == set(ConditionStatus)
    assert set(ALLERGY_TRANSITIONS) == set(AllergyStatus)
    with pytest.raises(ConflictError, match="cannot change from ACTIVE to SUSPECTED"):
        ensure_transition("Condition", "ACTIVE", ConditionStatus.SUSPECTED, CONDITION_TRANSITIONS)
    with pytest.raises(ConflictError, match="already ACTIVE"):
        ensure_transition("Allergy", "ACTIVE", AllergyStatus.ACTIVE, ALLERGY_TRANSITIONS)


# --- timeline params -----------------------------------------------------------------


def test_timeline_params():
    params = TimelineParams()
    assert (params.order, params.types, params.limit) == ("desc", None, 20)
    with pytest.raises(ValidationError, match="occurred_to cannot be before"):
        TimelineParams(occurred_from="2026-02-01T00:00:00Z", occurred_to="2026-01-01T00:00:00Z")
    with pytest.raises(ValidationError):
        TimelineParams(types=["imaging_study"])
    with pytest.raises(ValidationError):
        TimelineParams(order="newest")
    with pytest.raises(ValidationError):
        TimelineParams(occurred_from="2026-01-01T00:00:00")  # naive
