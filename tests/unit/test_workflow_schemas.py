"""Stage 4 request validation, staff-reference rule and workflow transition tables (no database)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.errors import ConflictError
from app.models.workflow import (
    ADMISSION_TRANSITIONS,
    APPOINTMENT_TRANSITIONS,
    TASK_TRANSITIONS,
    TRANSFERABLE_STATUSES,
    AdmissionStatus,
    AppointmentStatus,
    TaskStatus,
)
from app.schemas.clinical import ClinicalNoteCreate
from app.schemas.diagnostics import (
    LabOrderCreate,
    LabResultsSubmit,
    LabResultUpdate,
    LabSampleCreate,
    LabVerify,
    PrescriptionCreate,
    ReportCreate,
    ReportVerify,
)
from app.schemas.staff import DepartmentCreate, DepartmentUpdate, StaffCreate, StaffUpdate
from app.schemas.workflow import (
    AdmissionCreate,
    AdmissionDischarge,
    AdmissionTransferCreate,
    AppointmentCreate,
    AppointmentSearchParams,
    AppointmentStartConsultation,
    TaskCreate,
    TaskUpdate,
)
from app.services.clinical_common import ensure_transition

SID = str(uuid.uuid4())
FUTURE = (datetime.now(UTC) + timedelta(days=1)).isoformat()


# --- departments / staff -------------------------------------------------------------------


def staff(**overrides):
    return {"employee_code": "emp-0042", "first_name": "Grace", "last_name": "Mwangi", "designation": "NURSE",
            "department_id": SID, **overrides}


def test_staff_normalization():
    s = StaffCreate(**staff(phone="0044 20 7946 0958", email=" Grace.M@Hospital.ORG "))
    assert s.employee_code == "EMP-0042" and s.phone == "+442079460958" and s.email == "grace.m@hospital.org"


@pytest.mark.parametrize("overrides", [
    {"employee_code": "E"}, {"employee_code": "EMP 42"}, {"employee_code": "-EMP"}, {"employee_code": "X" * 21},
    {"designation": "SURGEON_GENERAL"}, {"first_name": " "}, {"department_id": "nope"}, {"email": "bad"},
    {"phone": "123"}, {"status": "ACTIVE"},
])
def test_invalid_staff(overrides):
    with pytest.raises(ValidationError):
        StaffCreate(**staff(**overrides))


def test_staff_update_rules():
    with pytest.raises(ValidationError, match="at least one field"):
        StaffUpdate()
    with pytest.raises(ValidationError, match="designation cannot be null"):
        StaffUpdate(designation=None)
    with pytest.raises(ValidationError):
        StaffUpdate(employee_code="NEW-1")  # immutable
    assert StaffUpdate(email=None).model_dump(exclude_unset=True) == {"email": None}


def test_department_rules():
    assert DepartmentCreate(name=" Pediatrics ").name == "Pediatrics"
    for bad in ({"name": ""}, {"name": "x" * 101}, {"status": "INACTIVE"}):
        with pytest.raises(ValidationError):
            DepartmentCreate(**bad)
    with pytest.raises(ValidationError):
        DepartmentUpdate(name=None)


# --- staff references replace free-text names (either/or, never both) --------------------------


PERSON_CASES = [
    (ClinicalNoteCreate, {"encounter_id": SID, "note_type": "PROGRESS", "content": "x"}, "author_name", "author_staff_id"),
    (LabOrderCreate, {"encounter_id": SID, "test_code": "fbc", "test_name": "FBC"}, "ordered_by", "ordered_by_staff_id"),
    (LabSampleCreate, {"specimen_type": "BLOOD"}, "collected_by", "collected_by_staff_id"),
    (LabResultsSubmit, {"results": [{"analyte_code": "hb", "analyte_name": "Hb", "value_numeric": 1}]},
     "entered_by", "entered_by_staff_id"),
    (LabResultUpdate, {"value_numeric": 1}, "entered_by", "entered_by_staff_id"),
    (LabVerify, {}, "verified_by", "verified_by_staff_id"),
    (ReportCreate, {"report_type": "OTHER", "title": "x"}, "author_name", "author_staff_id"),
    (ReportVerify, {}, "verified_by", "verified_by_staff_id"),
    (PrescriptionCreate, {"encounter_id": SID, "items": [{"medicine_name": "X", "dose_value": 1, "dose_unit": "mg",
                                                            "route": "ORAL", "frequency": "OD"}]},
     "prescriber_name", "prescriber_staff_id"),
]


@pytest.mark.parametrize(("schema", "base", "name_field", "staff_field"), PERSON_CASES)
def test_staff_id_or_legacy_name(schema, base, name_field, staff_field):
    assert getattr(schema(**base, **{staff_field: SID}), staff_field) == uuid.UUID(SID)
    assert getattr(schema(**base, **{name_field: "Dr. Legacy"}), name_field) == "Dr. Legacy"
    with pytest.raises(ValidationError, match="not both"):
        schema(**base, **{staff_field: SID, name_field: "Dr. Legacy"})
    # Stage 6: omitting both is valid at the schema level (the actor is bound from the login).
    assert getattr(schema(**base), staff_field) is None
    with pytest.raises(ValidationError):
        schema(**base, **{staff_field: "not-a-uuid"})


def test_report_requester_is_optional_but_not_both():
    base = {"report_type": "OTHER", "title": "x", "author_staff_id": SID}
    assert ReportCreate(**base).requested_by_staff_id is None
    with pytest.raises(ValidationError, match="not both"):
        ReportCreate(**base, requested_by="Dr. X", requested_by_staff_id=SID)


def test_result_update_needs_a_result_field_besides_the_person():
    with pytest.raises(ValidationError, match="at least one result field"):
        LabResultUpdate(entered_by_staff_id=SID)


# --- appointments / admissions / tasks -------------------------------------------------------------


def test_appointment_defaults_and_validation():
    a = AppointmentCreate(department_id=SID, reason="Review", scheduled_start=FUTURE)
    assert a.duration_minutes == 15 and a.staff_id is None
    for bad in ({"duration_minutes": 4}, {"duration_minutes": 481}, {"reason": " "},
                {"scheduled_start": "2026-10-01T09:00:00"}, {"status": "CONFIRMED"}):
        with pytest.raises(ValidationError):
            AppointmentCreate(**{"department_id": SID, "reason": "Review", "scheduled_start": FUTURE, **bad})
    assert AppointmentStartConsultation().encounter_type == "OPD"
    with pytest.raises(ValidationError):
        AppointmentStartConsultation(encounter_type="INPATIENT")
    with pytest.raises(ValidationError, match="scheduled_to cannot be before"):
        AppointmentSearchParams(scheduled_from="2026-10-02T00:00:00Z", scheduled_to="2026-10-01T00:00:00Z")


def test_admission_validation():
    base = {"department_id": SID, "admission_type": "EMERGENCY", "reason": "Sepsis", "requested_by_staff_id": SID}
    assert AdmissionCreate(**base).bed is None
    assert AdmissionCreate(**{**base, "requested_by_staff_id": None}).requested_by_staff_id is None  # Stage 6: bound
    for bad in ({"admission_type": "URGENT"}, {"requested_by_staff_id": "not-a-uuid"}, {"reason": ""},
                {"requested_at": FUTURE}, {"bed": "x" * 31}):
        with pytest.raises(ValidationError):
            AdmissionCreate(**{**base, **bad})
    with pytest.raises(ValidationError):
        AdmissionTransferCreate(to_department_id=SID)  # reason required
    with pytest.raises(ValidationError):
        AdmissionDischarge(disposition="CURED")
    assert AdmissionDischarge(disposition="HOME").discharged_at is None


def test_task_validation():
    t = TaskCreate(workflow_type="NURSING_CARE", title="Turn patient 2-hourly")
    assert t.priority == "NORMAL" and t.patient_id is None
    for bad in ({"workflow_type": "CLEANING"}, {"priority": "CRITICAL"}, {"title": ""}, {"status": "COMPLETED"}):
        with pytest.raises(ValidationError):
            TaskCreate(**{"workflow_type": "OTHER", "title": "x", **bad})
    with pytest.raises(ValidationError):
        TaskUpdate()
    with pytest.raises(ValidationError, match="priority cannot be null"):
        TaskUpdate(priority=None)


# --- transition tables ------------------------------------------------------------------------------


def test_tables_cover_every_status_with_expected_terminals():
    for table, enum, terminals in [
        (APPOINTMENT_TRANSITIONS, AppointmentStatus, {"COMPLETED", "CANCELLED", "NO_SHOW"}),
        (ADMISSION_TRANSITIONS, AdmissionStatus, {"DISCHARGED", "CANCELLED"}),
        (TASK_TRANSITIONS, TaskStatus, {"COMPLETED", "CANCELLED"}),
    ]:
        assert set(table) == set(enum)
        assert {s for s, targets in table.items() if not targets} == terminals


APPOINTMENT_PATH = ["REQUESTED", "CONFIRMED", "CHECKED_IN", "IN_CONSULTATION", "COMPLETED"]
ADMISSION_PATH = ["REQUESTED", "APPROVED", "ADMITTED", "TRANSFERRED", "DISCHARGED"]


@pytest.mark.parametrize(("table", "enum", "path"), [
    (APPOINTMENT_TRANSITIONS, AppointmentStatus, APPOINTMENT_PATH),
    (ADMISSION_TRANSITIONS, AdmissionStatus, ADMISSION_PATH),
    (TASK_TRANSITIONS, TaskStatus, ["OPEN", "ASSIGNED", "IN_PROGRESS", "COMPLETED"]),
])
def test_happy_paths(table, enum, path):
    for current, target in zip(path, path[1:]):
        ensure_transition("x", current, enum(target), table)


@pytest.mark.parametrize(("current", "target"), [
    ("REQUESTED", "CHECKED_IN"), ("REQUESTED", "NO_SHOW"), ("CONFIRMED", "IN_CONSULTATION"),
    ("CHECKED_IN", "NO_SHOW"), ("IN_CONSULTATION", "CANCELLED"), ("COMPLETED", "CANCELLED"),
    ("NO_SHOW", "CONFIRMED"), ("CANCELLED", "CONFIRMED"),
])
def test_invalid_appointment_transitions(current, target):
    with pytest.raises(ConflictError):
        ensure_transition("Appointment", current, AppointmentStatus(target), APPOINTMENT_TRANSITIONS)


@pytest.mark.parametrize(("current", "target"), [
    ("REQUESTED", "ADMITTED"), ("APPROVED", "DISCHARGED"), ("ADMITTED", "CANCELLED"),
    ("DISCHARGED", "ADMITTED"), ("CANCELLED", "APPROVED"), ("REQUESTED", "TRANSFERRED"),
])
def test_invalid_admission_transitions(current, target):
    with pytest.raises(ConflictError):
        ensure_transition("Admission", current, AdmissionStatus(target), ADMISSION_TRANSITIONS)


def test_transferable_statuses():
    assert TRANSFERABLE_STATUSES == {AdmissionStatus.ADMITTED, AdmissionStatus.TRANSFERRED}


@pytest.mark.parametrize(("current", "target"), [
    ("OPEN", "IN_PROGRESS"), ("OPEN", "COMPLETED"), ("ASSIGNED", "COMPLETED"), ("COMPLETED", "IN_PROGRESS"),
    ("CANCELLED", "ASSIGNED"),
])
def test_invalid_task_transitions(current, target):
    with pytest.raises(ConflictError):
        ensure_transition("Task", current, TaskStatus(target), TASK_TRANSITIONS)
