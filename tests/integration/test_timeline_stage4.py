"""Timeline integration of appointments, admissions, transfers and completed workflow tasks."""

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


def ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def kinds(body) -> list[str]:
    return [e["event_type"] for e in body["items"]]


@pytest.fixture
def setting(client, patient_payload, make_department, make_staff) -> dict:
    patient = ok(client.post("/api/patients", json=patient_payload(date_of_birth="1970-01-01")), 201)
    ward, icu, opd = make_department(name="Ward"), make_department(name="ICU"), make_department(name="OPD")
    doctor = make_staff(opd, first_name="D", last_name="Oc")
    nurse = make_staff(ward, first_name="N", last_name="Urse", designation="NURSE")
    return {"patient": patient, "ward": ward, "icu": icu, "opd": opd, "doctor": doctor, "nurse": nurse}


def timeline(client, patient, **params) -> dict:
    return ok(client.get(f"/api/patients/{patient['id']}/timeline", params={"limit": 100, **params}))


def test_admission_and_transfer_events(client, setting):
    p, doctor = setting["patient"], setting["doctor"]
    admission = ok(client.post(f"/api/patients/{p['id']}/admissions", json={
        "department_id": setting["ward"]["id"], "admission_type": "EMERGENCY", "reason": "Sepsis",
        "requested_by_staff_id": doctor["id"], "requested_at": ago(5)}), 201)
    [event] = timeline(client, p, types="admission")["items"]
    assert event["status"] == "REQUESTED" and event["title"] == "Emergency admission: Sepsis"
    assert event["occurred_at"] == admission["requested_at"]  # before admission: requested time

    ok(client.post(f"/api/admissions/{admission['id']}/approve", json={"approved_by_staff_id": doctor["id"]}))
    admitted = ok(client.post(f"/api/admissions/{admission['id']}/admit", json={"admitted_at": ago(4)}))
    ok(client.post(f"/api/admissions/{admission['id']}/transfer", json={
        "to_department_id": setting["icu"]["id"], "reason": "Shock", "transferred_at": ago(3)}))
    body = timeline(client, p, order="asc")
    assert kinds(body) == ["encounter", "admission", "admission_transfer"]
    admission_event = body["items"][1]
    assert admission_event["occurred_at"] == admitted["admitted_at"] and admission_event["status"] == "TRANSFERRED"
    assert admission_event["encounter_id"] == admitted["encounter_id"]
    assert body["items"][2]["title"] == "Transferred: Shock"
    # The INPATIENT encounter opened by the admission and the admission share the instant: encounter ranks first.
    assert body["items"][0]["occurred_at"] == admission_event["occurred_at"]


def test_appointment_events(client, setting):
    p = setting["patient"]
    future = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    appt = ok(client.post(f"/api/patients/{p['id']}/appointments", json={
        "department_id": setting["opd"]["id"], "staff_id": setting["doctor"]["id"], "reason": "Review",
        "scheduled_start": future}), 201)
    [event] = timeline(client, p)["items"]
    assert event["event_type"] == "appointment" and event["status"] == "REQUESTED"
    assert event["title"] == "Appointment: Review" and event["data"]["id"] == appt["id"]
    ok(client.post(f"/api/appointments/{appt['id']}/cancel", json={"reason": "Travelling"}))
    assert timeline(client, p)["items"][0]["status"] == "CANCELLED"


def test_only_completed_tasks_appear(client, setting):
    p, nurse = setting["patient"], setting["nurse"]
    task = ok(client.post("/api/workflow-tasks", json={
        "workflow_type": "NURSING_CARE", "title": "Pressure care", "patient_id": p["id"],
        "assigned_staff_id": nurse["id"]}), 201)
    ok(client.post("/api/workflow-tasks", json={"workflow_type": "ADMINISTRATIVE", "title": "General task"}), 201)
    assert timeline(client, p, types="workflow_task")["items"] == []
    ok(client.post(f"/api/workflow-tasks/{task['id']}/start"))
    done = ok(client.post(f"/api/workflow-tasks/{task['id']}/complete", json={"completion_notes": "Done"}))
    [event] = timeline(client, p, types="workflow_task")["items"]
    assert event["title"] == "Task completed: Pressure care" and event["occurred_at"] == done["completed_at"]
    assert event["encounter_id"] is None


def test_consultation_links_appointment_and_encounter_on_timeline(client, setting):
    p = setting["patient"]
    appt = ok(client.post(f"/api/patients/{p['id']}/appointments", json={
        "department_id": setting["opd"]["id"], "reason": "Walk-in", "scheduled_start": datetime.now(UTC).isoformat()}), 201)
    for step in ("confirm", "check-in", "start-consultation"):
        ok(client.post(f"/api/appointments/{appt['id']}/{step}"))
    body = timeline(client, p)
    by_type = {e["event_type"]: e for e in body["items"]}
    assert by_type["appointment"]["encounter_id"] == by_type["encounter"]["record_id"]
    assert set(kinds(body)) == {"appointment", "encounter"}


def test_new_types_are_filterable_and_patient_scoped(client, setting, patient_payload):
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Other")), 201)
    ok(client.post(f"/api/patients/{other['id']}/admissions", json={
        "department_id": setting["ward"]["id"], "admission_type": "ELECTIVE", "reason": "x",
        "requested_by_staff_id": setting["doctor"]["id"]}), 201)
    assert timeline(client, setting["patient"])["total"] == 0
    assert kinds(timeline(client, other, types=["admission", "appointment"])) == ["admission"]
    assert client.get(f"/api/patients/{other['id']}/timeline", params={"types": "staff"}).status_code == 422
