"""Stage 6 authenticated authorship: record actors come from the login, never from the client."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def as_(auth_client, user, method, path, body=None):
    return auth_client.request(method, path, json=body, headers=user["headers"])


@pytest.fixture
def team(make_user, make_department):
    ward = make_department(name="Ward")
    return {
        "doctor": make_user("DOCTOR", department=ward),
        "other_doctor": make_user("DOCTOR", department=ward),
        "nurse": make_user("NURSE", department=ward),
        "tech": make_user("LAB_TECHNICIAN", department=ward),
        "ward": ward,
    }


@pytest.fixture
def chart(auth_client, team):
    doctor = team["doctor"]
    patient = ok(as_(auth_client, doctor, "POST", "/api/patients", {
        "first_name": "Bound", "last_name": "Author", "date_of_birth": "1980-01-01", "sex": "MALE"}), 201)
    encounter = ok(as_(auth_client, doctor, "POST", f"/api/patients/{patient['id']}/encounters",
                       {"encounter_type": "OPD", "reason": "Review"}), 201)
    return {"patient": patient, "encounter": encounter, "P": f"/api/patients/{patient['id']}"}


def test_note_author_is_the_logged_in_staff(auth_client, team, chart):
    doctor = team["doctor"]
    body = {"encounter_id": chart["encounter"]["id"], "note_type": "PROGRESS", "content": "x"}
    note = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/clinical-notes", body), 201)
    assert note["author_staff_id"] == doctor["staff"]["id"] and note["author_name"] == doctor["staff"]["first_name"] + " Member"
    explicit_self = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/clinical-notes",
                           {**body, "author_staff_id": doctor["staff"]["id"]}), 201)
    assert explicit_self["author_staff_id"] == doctor["staff"]["id"]


@pytest.mark.parametrize("field", ["author_staff_id", "author_name"])
def test_note_impersonation_is_denied_and_audited(auth_client, team, chart, test_engine, field):
    doctor, other = team["doctor"], team["other_doctor"]
    value = other["staff"]["id"] if field == "author_staff_id" else "Dr. Somebody Else"
    response = as_(auth_client, doctor, "POST", f"{chart['P']}/clinical-notes", {
        "encounter_id": chart["encounter"]["id"], "note_type": "PROGRESS", "content": "x", field: value})
    assert response.status_code == 403
    assert ok(as_(auth_client, doctor, "GET", f"{chart['P']}/clinical-notes"))["total"] == 0
    with test_engine.connect() as c:
        outcome = c.execute(text(
            "SELECT outcome FROM audit_events WHERE action = 'POST /api/patients/{patient_id}/clinical-notes' "
            "AND actor_user_id = :u ORDER BY occurred_at DESC LIMIT 1"), {"u": doctor["user"]["id"]}).scalar_one()
    assert outcome == "DENIED"


def test_prescriber_and_lab_actors_are_bound(auth_client, team, chart):
    doctor, nurse, tech, other = team["doctor"], team["nurse"], team["tech"], team["other_doctor"]
    item = {"medicine_name": "Amoxicillin", "dose_value": 500, "dose_unit": "mg", "route": "ORAL", "frequency": "TID"}
    rx = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/prescriptions",
                {"encounter_id": chart["encounter"]["id"], "items": [item]}), 201)
    assert rx["prescriber_staff_id"] == doctor["staff"]["id"]
    assert as_(auth_client, doctor, "POST", f"{chart['P']}/prescriptions", {
        "encounter_id": chart["encounter"]["id"], "items": [item], "prescriber_staff_id": other["staff"]["id"]}
    ).status_code == 403

    order = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/lab-orders", {
        "encounter_id": chart["encounter"]["id"], "test_code": "fbc", "test_name": "FBC"}), 201)
    assert order["ordered_by_staff_id"] == doctor["staff"]["id"]
    sample = ok(as_(auth_client, nurse, "POST", f"/api/lab-orders/{order['id']}/samples",
                    {"specimen_type": "BLOOD"}), 201)
    assert sample["collected_by_staff_id"] == nurse["staff"]["id"]
    assert as_(auth_client, nurse, "POST", f"/api/lab-orders/{order['id']}/samples",
               {"specimen_type": "BLOOD", "collected_by": "Nurse Nobody"}).status_code == 403
    ok(as_(auth_client, tech, "POST", f"/api/lab-orders/{order['id']}/start-processing"))
    entered = ok(as_(auth_client, tech, "POST", f"/api/lab-orders/{order['id']}/results", {
        "results": [{"analyte_code": "hb", "analyte_name": "Hb", "value_numeric": 13, "unit": "g/dL"}]}))
    assert entered["results"][0]["entered_by_staff_id"] == tech["staff"]["id"]
    assert as_(auth_client, tech, "PATCH", f"/api/lab-results/{entered['results'][0]['id']}", {
        "value_numeric": 12, "entered_by_staff_id": doctor["staff"]["id"]}).status_code == 403


def test_report_author_and_verifier_are_bound(client, auth_client, team, chart):
    ok(client.post("/api/roles", json={"name": "RADIOLOGIST", "permissions": [
        {"code": "patient.view"}, {"code": "report.view"}, {"code": "report.create"}, {"code": "report.verify"}]}), 201)
    doctor, other = team["doctor"], team["other_doctor"]
    report = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/reports", {
        "report_type": "IMAGING", "title": "CXR", "content": "Clear", "requested_by_staff_id": other["staff"]["id"]}), 201)
    # Author is bound; the requester is a different clinician and stays client-chosen.
    assert report["author_staff_id"] == doctor["staff"]["id"]
    assert report["requested_by_staff_id"] == other["staff"]["id"]
    assert as_(auth_client, doctor, "POST", f"/api/reports/{report['id']}/verify",
               {"verified_by_staff_id": other["staff"]["id"]}).status_code == 403
    verified = ok(as_(auth_client, doctor, "POST", f"/api/reports/{report['id']}/verify", {}))
    assert verified["verified_by_staff_id"] == doctor["staff"]["id"]


def test_admission_actors_are_bound_but_attending_is_assignable(auth_client, team, chart, make_department):
    doctor, other = team["doctor"], team["other_doctor"]
    admission = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/admissions", {
        "department_id": team["ward"]["id"], "admission_type": "EMERGENCY", "reason": "Sepsis",
        "attending_staff_id": other["staff"]["id"]}), 201)
    assert admission["requested_by_staff_id"] == doctor["staff"]["id"]
    assert admission["attending_staff_id"] == other["staff"]["id"]  # assignment, not authorship
    assert as_(auth_client, other, "POST", f"/api/admissions/{admission['id']}/approve",
               {"approved_by_staff_id": doctor["staff"]["id"]}).status_code == 403
    approved = ok(as_(auth_client, other, "POST", f"/api/admissions/{admission['id']}/approve", {}))
    assert approved["approved_by_staff_id"] == other["staff"]["id"]
    ok(as_(auth_client, other, "POST", f"/api/admissions/{admission['id']}/admit", {}))
    icu = make_department(name="ICU")
    moved = ok(as_(auth_client, doctor, "POST", f"/api/admissions/{admission['id']}/transfer",
                   {"to_department_id": icu["id"], "reason": "Deteriorating"}))
    assert moved["transfers"][0]["transferred_by_staff_id"] == doctor["staff"]["id"]
    assert as_(auth_client, doctor, "POST", f"{chart['P']}/admissions", {
        "department_id": team["ward"]["id"], "admission_type": "ELECTIVE", "reason": "x",
        "requested_by_staff_id": other["staff"]["id"]}).status_code == 403


def test_task_creator_is_bound_assignee_is_not(auth_client, team):
    doctor, nurse = team["doctor"], team["nurse"]
    task = ok(as_(auth_client, doctor, "POST", "/api/workflow-tasks", {
        "workflow_type": "NURSING_CARE", "title": "Obs", "assigned_staff_id": nurse["staff"]["id"]}), 201)
    assert task["created_by_staff_id"] == doctor["staff"]["id"] and task["assigned_staff_id"] == nurse["staff"]["id"]
    assert as_(auth_client, doctor, "POST", "/api/workflow-tasks", {
        "workflow_type": "OTHER", "title": "x", "created_by_staff_id": nurse["staff"]["id"]}).status_code == 403


def test_encounter_attending_remains_assignable(auth_client, team, chart):
    doctor, other = team["doctor"], team["other_doctor"]
    encounter = ok(as_(auth_client, doctor, "POST", f"{chart['P']}/encounters", {
        "encounter_type": "FOLLOW_UP", "reason": "Handover", "attending_staff_id": other["staff"]["id"]}), 201)
    assert encounter["attending_staff_id"] == other["staff"]["id"]


def test_legacy_explicit_identity_is_kept_for_principals_without_staff(client, patient_payload):
    """The full-access test principal has no staff member (like a future importer): free text still works."""
    patient = ok(client.post("/api/patients", json=patient_payload()), 201)
    encounter = ok(client.post(f"/api/patients/{patient['id']}/encounters",
                               json={"encounter_type": "OPD", "reason": "x", "start_at": datetime.now(UTC).isoformat()}), 201)
    note = ok(client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "OTHER", "author_name": "Dr. Historical", "content": "x"}), 201)
    assert note["author_name"] == "Dr. Historical" and note["author_staff_id"] is None
    missing = client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "OTHER", "content": "x"})
    assert missing.status_code == 422 and missing.json()["detail"][0]["loc"] == ["body", "author_staff_id"]
