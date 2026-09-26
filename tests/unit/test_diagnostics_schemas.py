"""Stage 3 request validation, result interpretation and transition tables (no database)."""

import math
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core import clock
from app.core.errors import ConflictError
from app.models.clinical_base import format_identifier
from app.models.laboratory import LAB_ORDER_TRANSITIONS, LabOrderStatus
from app.models.prescription import PRESCRIPTION_TRANSITIONS, PrescriptionStatus
from app.models.report import REPORT_TRANSITIONS, ReportStatus
from app.schemas.diagnostics import (
    CancelRequest,
    LabOrderCreate,
    LabResultCreate,
    LabResultsSubmit,
    LabResultUpdate,
    LabSampleCreate,
    PrescriptionCreate,
    PrescriptionItemCreate,
    PrescriptionUpdate,
    ReportCreate,
    ReportUpdate,
    derive_interpretation,
)
from app.services.clinical_common import ensure_transition

PAST = "2026-01-10T09:00:00Z"


def future(minutes: int = 60) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


# --- identifiers / clock ---------------------------------------------------------------


@pytest.mark.parametrize(("prefix", "value", "expected"), [
    ("LAB-", 1, "LAB-000001"), ("SMP-", 123456, "SMP-123456"), ("RX-", 1234567, "RX-1234567")])
def test_format_identifier(prefix, value, expected):
    assert format_identifier(prefix, value) == expected


def test_format_identifier_rejects_zero():
    with pytest.raises(ValueError):
        format_identifier("LAB-", 0)


def test_now_not_before(monkeypatch):
    fixed = datetime(2026, 1, 1, 12, tzinfo=UTC)
    monkeypatch.setattr(clock, "utc_now", lambda: fixed)
    assert clock.now_not_before(None) == fixed
    assert clock.now_not_before(fixed - timedelta(hours=1)) == fixed
    assert clock.now_not_before(fixed + timedelta(minutes=3)) == fixed + timedelta(minutes=3)


# --- lab orders / samples --------------------------------------------------------------


def order(**overrides):
    return {"encounter_id": str(uuid.uuid4()), "test_code": "full_blood_count", "test_name": "Full blood count",
            "ordered_by": "Dr. A", **overrides}


def test_lab_order_defaults():
    o = LabOrderCreate(**order(test_code=" Malaria_RDT "))
    assert o.test_code == "malaria_rdt" and o.priority == "ROUTINE" and o.ordered_at is None


@pytest.mark.parametrize("overrides", [
    {"encounter_id": None}, {"encounter_id": "nope"}, {"test_code": "Full Blood Count"}, {"test_code": "1abc"},
    {"test_name": " "}, {"ordered_by": ""}, {"priority": "ASAP"}, {"ordered_at": future()},
    {"ordered_at": "2026-01-10T09:00:00"}, {"code_system": "http://loinc.org"}, {"status": "RELEASED"},
])
def test_invalid_lab_order(overrides):
    with pytest.raises(ValidationError):
        LabOrderCreate(**order(**overrides))


@pytest.mark.parametrize("overrides", [{"specimen_type": "SALIVA"}, {"collected_by": " "}, {"collected_at": future()}])
def test_invalid_sample(overrides):
    with pytest.raises(ValidationError):
        LabSampleCreate(**{"specimen_type": "BLOOD", "collected_by": "Nurse B", **overrides})


# --- lab results -------------------------------------------------------------------------


def result(**overrides):
    return {"analyte_code": "hemoglobin", "analyte_name": "Hemoglobin", "value_numeric": 13.5, "unit": "g/dL",
            "reference_low": 12, "reference_high": 16, **overrides}


@pytest.mark.parametrize(("value", "low", "high", "expected"), [
    (13.5, 12, 16, "NORMAL"), (12, 12, 16, "NORMAL"), (16, 12, 16, "NORMAL"),
    (9.1, 12, 16, "LOW"), (17, 12, 16, "HIGH"), (5, None, 10, "NORMAL"), (11, None, 10, "HIGH"),
    (1, 2, None, "LOW"), (1, None, None, None), (None, 1, 2, None),
])
def test_derive_interpretation(value, low, high, expected):
    assert derive_interpretation(value, low, high) == expected


def test_result_interpretation_derived_unless_given():
    assert LabResultCreate(**result(value_numeric=9.1)).interpretation == "LOW"
    assert LabResultCreate(**result(value_numeric=5.0, interpretation="CRITICAL_LOW")).interpretation == "CRITICAL_LOW"


def test_text_result():
    r = LabResultCreate(analyte_code="malaria_rdt", analyte_name="Malaria RDT", value_text="Positive (P. falciparum)",
                        reference_text="Negative", interpretation="ABNORMAL")
    assert r.value_numeric is None and r.unit is None


@pytest.mark.parametrize(("overrides", "message"), [
    ({"value_numeric": None}, "exactly one of"),
    ({"value_text": "13.5"}, "exactly one of"),
    ({"value_numeric": math.nan}, "finite"),
    ({"reference_low": math.inf}, "finite"),
    ({"reference_low": 20}, "reference_low cannot be greater"),
    ({"value_numeric": None, "value_text": "pos", "unit": None}, "reference_low/reference_high are only allowed"),
    ({"value_numeric": None, "value_text": "pos", "reference_low": None, "reference_high": None}, "unit is only allowed"),
    ({"analyte_code": "h b"}, "pattern"),
    ({"interpretation": "WEIRD"}, "interpretation"),
    ({"system_code": "718-7"}, "given together"),
    ({"resulted_at": future()}, "future"),
])
def test_invalid_results(overrides, message):
    with pytest.raises(ValidationError, match=message):
        LabResultCreate(**result(**overrides))


def test_result_submission_rules():
    ok = LabResultsSubmit(entered_by="Tech C", results=[result(), result(analyte_code="wbc", analyte_name="WBC")])
    assert len(ok.results) == 2
    with pytest.raises(ValidationError, match="only once"):
        LabResultsSubmit(entered_by="Tech C", results=[result(), result()])
    with pytest.raises(ValidationError):
        LabResultsSubmit(entered_by="Tech C", results=[])
    # Stage 6: the technician may be omitted; it is bound from the login (service requires it otherwise).
    assert LabResultsSubmit(results=[result()]).entered_by_staff_id is None


def test_result_update_requires_a_result_field():
    with pytest.raises(ValidationError, match="at least one result field"):
        LabResultUpdate(entered_by="Tech C")
    assert LabResultUpdate(value_numeric=12).entered_by is None  # Stage 6: bound from the login
    with pytest.raises(ValidationError):
        LabResultUpdate(entered_by="x", analyte_code="other")  # analyte identity is fixed
    assert LabResultUpdate(entered_by="Tech C", value_numeric=12).model_dump(exclude_unset=True) == {
        "entered_by": "Tech C", "value_numeric": 12}


# --- reports ------------------------------------------------------------------------------


def report(**overrides):
    return {"report_type": "IMAGING", "title": "Chest X-ray", "author_name": "Dr. R", **overrides}


def test_report_defaults():
    r = ReportCreate(**report())
    assert r.content is None and r.lab_order_id is None and r.effective_at is None


@pytest.mark.parametrize("overrides", [
    {"report_type": "XRAY"}, {"title": ""}, {"author_name": " "}, {"status": "RELEASED"},
    {"lab_order_id": str(uuid.uuid4())},  # only for LABORATORY
    {"code": "24627-2"}, {"effective_at": future()}, {"requested_at": "2026-01-01T00:00:00"},
])
def test_invalid_report(overrides):
    with pytest.raises(ValidationError):
        ReportCreate(**report(**overrides))


def test_laboratory_report_may_reference_order():
    assert ReportCreate(**report(report_type="LABORATORY", lab_order_id=str(uuid.uuid4()))).lab_order_id


def test_report_update_rules():
    with pytest.raises(ValidationError):
        ReportUpdate()
    with pytest.raises(ValidationError, match="title cannot be null"):
        ReportUpdate(title=None)
    with pytest.raises(ValidationError):
        ReportUpdate(status="RELEASED")
    assert ReportUpdate(content=" Findings ").content == "Findings"


# --- prescriptions ------------------------------------------------------------------------


def item(**overrides):
    return {"medicine_name": "Amoxicillin 500 mg capsule", "dose_value": 500, "dose_unit": "mg", "route": "ORAL",
            "frequency": "TID", "duration_value": 7, "duration_unit": "DAYS", "quantity": 21,
            "quantity_unit": "capsule", **overrides}


def test_valid_item_and_prescription():
    rx = PrescriptionCreate(encounter_id=str(uuid.uuid4()), prescriber_name="Dr. P", items=[item(), item(
        medicine_name="Paracetamol 500 mg tablet", dose_value=1000, frequency="PRN", duration_value=None,
        duration_unit=None, quantity=None, quantity_unit=None, instructions="For fever > 38.5 C; max 4 g/day")])
    assert len(rx.items) == 2


@pytest.mark.parametrize(("overrides", "message"), [
    ({"dose_value": 0}, "greater than 0"),
    ({"dose_value": -5}, "greater than 0"),
    ({"dose_value": math.inf}, "dose_value"),
    ({"dose_unit": " "}, "dose_unit"),
    ({"route": "BY_MOUTH"}, "route"),
    ({"frequency": "THRICE"}, "frequency"),
    ({"duration_unit": None}, "given together"),
    ({"duration_value": 0}, "greater than 0"),
    ({"duration_value": 4000}, "cannot exceed 3650 DAYS"),
    ({"duration_value": 200, "duration_unit": "MONTHS"}, "cannot exceed 120 MONTHS"),
    ({"quantity": 0}, "greater than 0"),
    ({"quantity": None}, "quantity_unit requires quantity"),
    ({"frequency": "PRN"}, "PRN"),
    ({"code": "308182"}, "given together"),
    ({"medicine_name": ""}, "medicine_name"),
])
def test_invalid_items(overrides, message):
    with pytest.raises(ValidationError, match=message):
        PrescriptionItemCreate(**item(**overrides))


@pytest.mark.parametrize("overrides", [
    {"items": []}, {"items": [item()] * 51}, {"prescriber_name": ""}, {"encounter_id": None},
    {"prescribed_at": future()}, {"status": "ACTIVE"},
])
def test_invalid_prescription(overrides):
    with pytest.raises(ValidationError):
        PrescriptionCreate(**{"encounter_id": str(uuid.uuid4()), "prescriber_name": "Dr. P", "items": [item()],
                              **overrides})


def test_prescription_update_and_cancel_bodies():
    assert PrescriptionUpdate(notes=None).notes is None
    with pytest.raises(ValidationError):
        PrescriptionUpdate()
    with pytest.raises(ValidationError):
        CancelRequest(reason="")


# --- transitions ---------------------------------------------------------------------------


LAB_PATH = ["ORDERED", "SAMPLE_COLLECTED", "PROCESSING", "RESULT_ENTERED", "VERIFIED", "RELEASED"]


def test_lab_happy_path_is_allowed():
    for current, target in zip(LAB_PATH, LAB_PATH[1:]):
        ensure_transition("Lab order", current, LabOrderStatus(target), LAB_ORDER_TRANSITIONS)


@pytest.mark.parametrize(("current", "target"), [
    ("ORDERED", "PROCESSING"), ("ORDERED", "VERIFIED"), ("SAMPLE_COLLECTED", "RESULT_ENTERED"),
    ("PROCESSING", "VERIFIED"), ("RESULT_ENTERED", "RELEASED"), ("VERIFIED", "CANCELLED"),
    ("RELEASED", "CANCELLED"), ("CANCELLED", "ORDERED"), ("VERIFIED", "RESULT_ENTERED"),
])
def test_invalid_lab_transitions(current, target):
    with pytest.raises(ConflictError):
        ensure_transition("Lab order", current, LabOrderStatus(target), LAB_ORDER_TRANSITIONS)


def test_transition_tables_cover_every_status_and_terminals():
    assert set(LAB_ORDER_TRANSITIONS) == set(LabOrderStatus)
    assert set(REPORT_TRANSITIONS) == set(ReportStatus)
    assert set(PRESCRIPTION_TRANSITIONS) == set(PrescriptionStatus)
    for table, terminals in [
        (LAB_ORDER_TRANSITIONS, {"RELEASED", "CANCELLED"}),
        (REPORT_TRANSITIONS, {"RELEASED", "CANCELLED"}),
        (PRESCRIPTION_TRANSITIONS, {"COMPLETED", "CANCELLED"}),
    ]:
        assert {status for status, targets in table.items() if not targets} == terminals


@pytest.mark.parametrize(("current", "target", "allowed"), [
    ("DRAFT", "ACTIVE", True), ("DRAFT", "COMPLETED", False), ("DRAFT", "ON_HOLD", False),
    ("ACTIVE", "ON_HOLD", True), ("ON_HOLD", "ACTIVE", True), ("ON_HOLD", "COMPLETED", False),
    ("ACTIVE", "COMPLETED", True), ("COMPLETED", "ACTIVE", False), ("CANCELLED", "ACTIVE", False),
    ("ACTIVE", "DRAFT", False),
])
def test_prescription_transitions(current, target, allowed):
    if allowed:
        ensure_transition("Rx", current, PrescriptionStatus(target), PRESCRIPTION_TRANSITIONS)
    else:
        with pytest.raises(ConflictError):
            ensure_transition("Rx", current, PrescriptionStatus(target), PRESCRIPTION_TRANSITIONS)


@pytest.mark.parametrize(("current", "target", "allowed"), [
    ("DRAFT", "VERIFIED", True), ("DRAFT", "RELEASED", False), ("VERIFIED", "RELEASED", True),
    ("VERIFIED", "DRAFT", False), ("RELEASED", "CANCELLED", False), ("VERIFIED", "CANCELLED", True),
])
def test_report_transitions(current, target, allowed):
    if allowed:
        ensure_transition("Report", current, ReportStatus(target), REPORT_TRANSITIONS)
    else:
        with pytest.raises(ConflictError):
            ensure_transition("Report", current, ReportStatus(target), REPORT_TRANSITIONS)


def test_past_literal_is_valid_timestamp():
    assert LabSampleCreate(specimen_type="URINE", collected_by="N", collected_at=PAST).collected_at.tzinfo is not None
