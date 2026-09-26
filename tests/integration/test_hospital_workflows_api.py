"""Appointments, admissions and workflow tasks end-to-end against hms_test."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def soon(hours: float = 2) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1985-05-05")), 201)


@pytest.fixture
def opd(make_department) -> dict:
    return make_department(name="Outpatients")


@pytest.fixture
def doctor(make_staff, opd) -> dict:
    return make_staff(opd, first_name="Wanjiru", last_name="Kamau", designation="DOCTOR")


# ==== appointments ================================================================================


@pytest.fixture
def appointment(client, patient, opd, doctor) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/appointments", json={
        "department_id": opd["id"], "staff_id": doctor["id"], "reason": "Hypertension review",
        "scheduled_start": soon(), "duration_minutes": 20}), 201)


def appt(client, appointment, action, body=None):
    return client.post(f"/api/appointments/{appointment['id']}/{action}", json=body)


def test_appointment_full_lifecycle_creates_and_finishes_encounter(client, appointment, patient, doctor):
    assert appointment["status"] == "REQUESTED" and appointment["encounter_id"] is None
    assert ok(appt(client, appointment, "confirm"))["confirmed_at"]
    assert ok(appt(client, appointment, "check-in"))["status"] == "CHECKED_IN"
    started = ok(appt(client, appointment, "start-consultation", {"encounter_type": "FOLLOW_UP"}))
    assert started["status"] == "IN_CONSULTATION" and started["encounter_id"]
    encounter = ok(client.get(f"/api/encounters/{started['encounter_id']}"))
    assert encounter["status"] == "IN_PROGRESS" and encounter["encounter_type"] == "FOLLOW_UP"
    assert encounter["attending_staff_id"] == doctor["id"] and encounter["patient_id"] == patient["id"]
    assert encounter["reason"] == "Hypertension review"

    done = ok(appt(client, appointment, "complete", {"summary": "BP controlled"}))
    assert done["status"] == "COMPLETED" and done["completed_at"] >= done["consultation_started_at"]
    encounter = ok(client.get(f"/api/encounters/{started['encounter_id']}"))
    assert encounter["status"] == "FINISHED" and encounter["summary"] == "BP controlled"


def test_complete_leaves_already_closed_encounter_alone(client, appointment):
    for step in ("confirm", "check-in", "start-consultation"):
        ok(appt(client, appointment, step))
    encounter_id = ok(client.get(f"/api/appointments/{appointment['id']}"))["encounter_id"]
    ok(client.post(f"/api/encounters/{encounter_id}/finish", json={"summary": "closed by clinician"}))
    ok(appt(client, appointment, "complete", {"summary": "ignored"}))
    assert ok(client.get(f"/api/encounters/{encounter_id}"))["summary"] == "closed by clinician"


@pytest.mark.parametrize(("reach", "action", "body"), [
    ([], "check-in", None), ([], "start-consultation", None), ([], "complete", None), ([], "no-show", None),
    (["confirm"], "confirm", None), (["confirm"], "start-consultation", None),
    (["confirm", "check-in"], "no-show", None), (["confirm", "check-in", "start-consultation"], "cancel", {"reason": "x"}),
    (["confirm", "check-in", "start-consultation", "complete"], "cancel", {"reason": "x"}),
    (["confirm", "no-show"], "check-in", None), (["cancel"], "confirm", None),
])
def test_invalid_appointment_transitions_are_409(client, appointment, reach, action, body):
    for step in reach:
        ok(appt(client, appointment, step, {"reason": "setup"} if step == "cancel" else None))
    before = ok(client.get(f"/api/appointments/{appointment['id']}"))
    assert appt(client, appointment, action, body).status_code == 409
    assert ok(client.get(f"/api/appointments/{appointment['id']}")) == before


@pytest.mark.parametrize("reach", [[], ["confirm"], ["confirm", "check-in"]])
def test_cancellation_paths(client, appointment, reach):
    for step in reach:
        ok(appt(client, appointment, step))
    cancelled = ok(appt(client, appointment, "cancel", {"reason": "Patient request"}))
    assert cancelled["status"] == "CANCELLED" and cancelled["cancellation_reason"] == "Patient request"


def test_no_show(client, appointment):
    ok(appt(client, appointment, "confirm"))
    assert ok(appt(client, appointment, "no-show"))["no_show_at"]


def test_appointment_reference_validation(client, patient, opd, doctor, make_department, make_staff):
    url = f"/api/patients/{patient['id']}/appointments"
    body = {"department_id": opd["id"], "reason": "x", "scheduled_start": soon()}
    other_dept_doctor = make_staff(make_department(name="Surgery"))
    assert client.post(url, json={**body, "staff_id": other_dept_doctor["id"]}).status_code == 422
    assert client.post(url, json={**body, "staff_id": str(uuid.uuid4())}).status_code == 422
    assert client.post(url, json={**body, "department_id": str(uuid.uuid4())}).status_code == 422
    assert client.post(url, json={**body, "scheduled_start": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}
                       ).status_code == 422
    ok(client.post(f"/api/staff/{doctor['id']}/deactivate"))
    assert client.post(url, json={**body, "staff_id": doctor["id"]}).status_code == 409
    ok(client.post(f"/api/departments/{opd['id']}/deactivate"))
    assert client.post(url, json=body).status_code == 409
    assert client.post(f"/api/patients/{uuid.uuid4()}/appointments", json=body).status_code == 404


def test_inactive_patient_cannot_book_or_check_in(client, appointment, patient, opd):
    ok(appt(client, appointment, "confirm"))
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Transferred"}))
    assert appt(client, appointment, "check-in").status_code == 409
    body = {"department_id": opd["id"], "reason": "x", "scheduled_start": soon()}
    assert client.post(f"/api/patients/{patient['id']}/appointments", json=body).status_code == 409
    assert ok(appt(client, appointment, "cancel", {"reason": "Patient transferred"}))["status"] == "CANCELLED"


def test_schedule_search(client, patient, opd, doctor, make_staff):
    nurse = make_staff(opd, designation="NURSE")
    a = ok(client.post(f"/api/patients/{patient['id']}/appointments", json={
        "department_id": opd["id"], "staff_id": doctor["id"], "reason": "later", "scheduled_start": soon(5)}), 201)
    b = ok(client.post(f"/api/patients/{patient['id']}/appointments", json={
        "department_id": opd["id"], "staff_id": nurse["id"], "reason": "sooner", "scheduled_start": soon(1)}), 201)
    schedule = ok(client.get("/api/appointments", params={"department_id": opd["id"]}))
    assert [x["id"] for x in schedule["items"]] == [b["id"], a["id"]]  # chronological
    assert ok(client.get("/api/appointments", params={"staff_id": doctor["id"]}))["items"][0]["id"] == a["id"]
    window = ok(client.get("/api/appointments", params={"scheduled_to": soon(3)}))
    assert [x["id"] for x in window["items"]] == [b["id"]]
    patient_list = ok(client.get(f"/api/patients/{patient['id']}/appointments"))
    assert [x["id"] for x in patient_list["items"]] == [a["id"], b["id"]]  # newest first


# ==== admissions ==================================================================================


@pytest.fixture
def ward(make_department) -> dict:
    return make_department(name="Medical Ward")


@pytest.fixture
def admission(client, patient, ward, doctor) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/admissions", json={
        "department_id": ward["id"], "admission_type": "EMERGENCY", "reason": "Severe pneumonia",
        "requested_by_staff_id": doctor["id"], "bed": "B-12"}), 201)


def adm(client, admission, action, body=None):
    return client.post(f"/api/admissions/{admission['id']}/{action}", json=body)


def test_admission_full_lifecycle(client, admission, doctor, ward, make_department, make_staff):
    assert admission["status"] == "REQUESTED" and admission["requested_by_staff_id"] == doctor["id"]
    approver = make_staff(designation="CLINICAL_OFFICER")
    approved = ok(adm(client, admission, "approve", {"approved_by_staff_id": approver["id"]}))
    assert approved["status"] == "APPROVED" and approved["approved_by_staff_id"] == approver["id"]

    admitted = ok(adm(client, admission, "admit", {"attending_staff_id": doctor["id"], "bed": "B-14"}))
    assert admitted["status"] == "ADMITTED" and admitted["bed"] == "B-14" and admitted["encounter_id"]
    encounter = ok(client.get(f"/api/encounters/{admitted['encounter_id']}"))
    assert encounter["encounter_type"] == "INPATIENT" and encounter["status"] == "IN_PROGRESS"
    assert encounter["attending_staff_id"] == doctor["id"]

    icu = make_department(name="ICU")
    moved = ok(adm(client, admission, "transfer", {"to_department_id": icu["id"], "to_bed": "ICU-2",
                                                   "reason": "Respiratory failure"}))
    assert moved["status"] == "TRANSFERRED" and moved["department_id"] == icu["id"] and moved["bed"] == "ICU-2"
    back = ok(adm(client, admission, "transfer", {"to_department_id": ward["id"], "reason": "Stable"}))
    assert back["department_id"] == ward["id"] and back["bed"] is None and back["status"] == "TRANSFERRED"
    assert [(t["from_bed"], t["to_bed"]) for t in back["transfers"]] == [("B-14", "ICU-2"), ("ICU-2", None)]

    discharged = ok(adm(client, admission, "discharge", {"disposition": "HOME", "discharge_summary": "Recovered"}))
    assert discharged["status"] == "DISCHARGED" and discharged["discharge_disposition"] == "HOME"
    encounter = ok(client.get(f"/api/encounters/{admitted['encounter_id']}"))
    assert encounter["status"] == "FINISHED" and encounter["summary"] == "Recovered"


def test_discharge_directly_from_admitted(client, admission, doctor):
    ok(adm(client, admission, "approve", {"approved_by_staff_id": doctor["id"]}))
    ok(adm(client, admission, "admit"))
    assert ok(adm(client, admission, "discharge", {"disposition": "REFERRED_OUT"}))["status"] == "DISCHARGED"


@pytest.mark.parametrize(("reach", "action", "body"), [
    ([], "admit", None), ([], "discharge", {"disposition": "HOME"}), ([], "transfer", "ICU"),
    (["approve"], "approve", "APPROVER"), (["approve"], "discharge", {"disposition": "HOME"}),
    (["approve", "admit"], "cancel", {"reason": "x"}), (["approve", "admit"], "admit", None),
    (["approve", "admit", "discharge"], "transfer", "ICU"), (["cancel"], "approve", "APPROVER"),
])
def test_invalid_admission_transitions_are_409(client, admission, doctor, make_department, reach, action, body):
    bodies = {"approve": {"approved_by_staff_id": doctor["id"]}, "discharge": {"disposition": "HOME"},
              "cancel": {"reason": "setup"}, "admit": None}
    for step in reach:
        ok(adm(client, admission, step, bodies[step]))
    if body == "ICU":
        body = {"to_department_id": make_department(name="ICU")["id"], "reason": "x"}
    elif body == "APPROVER":
        body = {"approved_by_staff_id": doctor["id"]}
    before = ok(client.get(f"/api/admissions/{admission['id']}"))
    assert adm(client, admission, action, body).status_code == 409
    assert ok(client.get(f"/api/admissions/{admission['id']}")) == before


def test_one_open_admission_per_patient(client, admission, patient, ward, doctor):
    body = {"department_id": ward["id"], "admission_type": "ELECTIVE", "reason": "x",
            "requested_by_staff_id": doctor["id"]}
    assert client.post(f"/api/patients/{patient['id']}/admissions", json=body).status_code == 409
    ok(adm(client, admission, "cancel", {"reason": "Bed not needed"}))
    ok(client.post(f"/api/patients/{patient['id']}/admissions", json=body), 201)


def test_transfer_must_change_location_and_times_move_forward(client, patient, ward, doctor):
    def ago(hours):
        return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()

    admission = ok(client.post(f"/api/patients/{patient['id']}/admissions", json={
        "department_id": ward["id"], "admission_type": "ELECTIVE", "reason": "x", "bed": "B-12",
        "requested_by_staff_id": doctor["id"], "requested_at": ago(3)}), 201)
    ok(adm(client, admission, "approve", {"approved_by_staff_id": doctor["id"]}))
    assert adm(client, admission, "admit", {"admitted_at": ago(4)}).status_code == 422  # before the request
    ok(adm(client, admission, "admit", {"admitted_at": ago(2)}))
    same = {"to_department_id": ward["id"], "to_bed": "B-12", "reason": "x"}
    assert adm(client, admission, "transfer", same).status_code == 422
    early = {"to_department_id": ward["id"], "to_bed": "B-1", "reason": "x", "transferred_at": ago(2.5)}
    assert adm(client, admission, "transfer", early).status_code == 422
    ok(adm(client, admission, "transfer", {**early, "transferred_at": ago(1)}))
    assert adm(client, admission, "discharge", {"disposition": "HOME", "discharged_at": ago(1.5)}).status_code == 422
    assert ok(adm(client, admission, "discharge", {"disposition": "HOME"}))["status"] == "DISCHARGED"


def test_admission_reference_validation(client, patient, ward, doctor):
    url = f"/api/patients/{patient['id']}/admissions"
    body = {"department_id": ward["id"], "admission_type": "ELECTIVE", "reason": "x",
            "requested_by_staff_id": doctor["id"]}
    assert client.post(url, json={**body, "requested_by_staff_id": str(uuid.uuid4())}).status_code == 422
    assert client.post(url, json={**body, "attending_staff_id": str(uuid.uuid4())}).status_code == 422
    assert client.post(url, json={**body, "department_id": str(uuid.uuid4())}).status_code == 422
    ok(client.post(f"/api/departments/{ward['id']}/deactivate"))
    assert client.post(url, json=body).status_code == 409


def test_ward_census(client, admission, doctor, ward):
    ok(adm(client, admission, "approve", {"approved_by_staff_id": doctor["id"]}))
    ok(adm(client, admission, "admit"))
    census = ok(client.get("/api/admissions", params={"department_id": ward["id"], "status": "ADMITTED"}))
    assert [a["id"] for a in census["items"]] == [admission["id"]]
    assert ok(client.get("/api/admissions", params={"status": "DISCHARGED"}))["total"] == 0


# ==== workflow tasks ===============================================================================


def task(client, **overrides) -> dict:
    return ok(client.post("/api/workflow-tasks", json={"workflow_type": "NURSING_CARE", "title": "Wound dressing",
                                                        **overrides}), 201)


def test_task_lifecycle(client, patient, make_staff, doctor):
    nurse = make_staff(designation="NURSE")
    t = task(client, patient_id=patient["id"], priority="HIGH", created_by_staff_id=doctor["id"], due_at=soon(4))
    assert t["status"] == "OPEN" and t["assigned_staff_id"] is None
    assigned = ok(client.post(f"/api/workflow-tasks/{t['id']}/assign", json={"staff_id": nurse["id"]}))
    assert assigned["status"] == "ASSIGNED" and assigned["assigned_staff_id"] == nurse["id"]
    started = ok(client.post(f"/api/workflow-tasks/{t['id']}/start"))
    assert started["status"] == "IN_PROGRESS" and started["started_at"]
    other = make_staff(designation="NURSE")
    reassigned = ok(client.post(f"/api/workflow-tasks/{t['id']}/assign", json={"staff_id": other["id"]}))
    assert reassigned["status"] == "IN_PROGRESS" and reassigned["assigned_staff_id"] == other["id"]
    done = ok(client.post(f"/api/workflow-tasks/{t['id']}/complete", json={"completion_notes": "Dressing changed"}))
    assert done["status"] == "COMPLETED" and done["completion_notes"] == "Dressing changed"


def test_task_created_already_assigned(client, make_staff):
    nurse = make_staff()
    t = task(client, assigned_staff_id=nurse["id"])
    assert t["status"] == "ASSIGNED" and t["assigned_at"]


@pytest.mark.parametrize(("reach", "action", "body"), [
    ([], "start", None), ([], "complete", None),
    (["assign"], "complete", None), (["assign", "start", "complete"], "cancel", {"reason": "x"}),
    (["assign", "start", "complete"], "assign", "STAFF"), (["cancel"], "start", None), (["cancel"], "assign", "STAFF"),
])
def test_invalid_task_transitions_are_409(client, make_staff, reach, action, body):
    nurse = make_staff()
    t = task(client)
    bodies = {"assign": {"staff_id": nurse["id"]}, "cancel": {"reason": "setup"}}
    for step in reach:
        ok(client.post(f"/api/workflow-tasks/{t['id']}/{step}", json=bodies.get(step)))
    if body == "STAFF":
        body = {"staff_id": make_staff()["id"]}
    assert client.post(f"/api/workflow-tasks/{t['id']}/{action}", json=body).status_code == 409


def test_reassign_to_same_staff_is_409(client, make_staff):
    nurse = make_staff()
    t = task(client, assigned_staff_id=nurse["id"])
    assert client.post(f"/api/workflow-tasks/{t['id']}/assign", json={"staff_id": nurse["id"]}).status_code == 409


def test_task_references_and_edits(client, make_staff, make_department):
    assert client.post("/api/workflow-tasks", json={"workflow_type": "OTHER", "title": "x",
                                                    "patient_id": str(uuid.uuid4())}).status_code == 422
    assert client.post("/api/workflow-tasks", json={"workflow_type": "OTHER", "title": "x",
                                                    "assigned_staff_id": str(uuid.uuid4())}).status_code == 422
    inactive = make_staff()
    ok(client.post(f"/api/staff/{inactive['id']}/deactivate"))
    t = task(client)
    assert client.post(f"/api/workflow-tasks/{t['id']}/assign", json={"staff_id": inactive["id"]}).status_code == 409
    edited = ok(client.patch(f"/api/workflow-tasks/{t['id']}", json={"priority": "URGENT", "title": "Urgent dressing"}))
    assert edited["priority"] == "URGENT"
    ok(client.post(f"/api/workflow-tasks/{t['id']}/cancel", json={"reason": "Duplicate"}))
    assert client.patch(f"/api/workflow-tasks/{t['id']}", json={"priority": "LOW"}).status_code == 409


def test_work_queue_order_and_filters(client, make_staff, patient):
    nurse = make_staff()
    low = task(client, title="low", priority="LOW")
    urgent_late = task(client, title="urgent-late", priority="URGENT", due_at=soon(10), assigned_staff_id=nurse["id"])
    urgent_soon = task(client, title="urgent-soon", priority="URGENT", due_at=soon(1), patient_id=patient["id"])
    normal = task(client, title="normal")
    queue = ok(client.get("/api/workflow-tasks"))
    assert [t["title"] for t in queue["items"]] == ["urgent-soon", "urgent-late", "normal", "low"]
    assert ok(client.get("/api/workflow-tasks", params={"assigned_staff_id": nurse["id"]}))["items"][0]["id"] == urgent_late["id"]
    assert ok(client.get("/api/workflow-tasks", params={"patient_id": patient["id"]}))["total"] == 1
    assert ok(client.get("/api/workflow-tasks", params={"status": "OPEN"}))["total"] == 3
    assert {low["id"], normal["id"]} <= {t["id"] for t in queue["items"]}


@pytest.mark.parametrize("path", ["appointments", "admissions", "workflow-tasks"])
def test_missing_invalid_and_no_delete(client, path):
    assert client.get(f"/api/{path}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/{path}/bad-id").status_code == 422
    assert client.post(f"/api/{path}/{uuid.uuid4()}/cancel", json={"reason": "x"}).status_code == 404
    assert client.delete(f"/api/{path}/{uuid.uuid4()}").status_code == 405
