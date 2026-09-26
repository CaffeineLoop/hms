"""Prescriptions end-to-end against the isolated test database (hms_test)."""

import re
import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

T0 = "2026-05-05T09:00:00Z"
AMOXICILLIN = {
    "medicine_name": "Amoxicillin 500 mg capsule", "code_system": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "code": "308182", "dose_value": 500, "dose_unit": "mg", "route": "ORAL", "frequency": "TID",
    "duration_value": 7, "duration_unit": "DAYS", "quantity": 21, "quantity_unit": "capsule",
    "instructions": "Take with water; complete the course.",
}
PARACETAMOL = {
    "medicine_name": "Paracetamol 500 mg tablet", "dose_value": 1000, "dose_unit": "mg", "route": "ORAL",
    "frequency": "PRN", "instructions": "For fever or pain; max 4 g per 24 h.",
}


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1990-09-09")), 201)


@pytest.fixture
def encounter(client, patient) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/encounters",
                          json={"encounter_type": "OPD", "reason": "Sore throat", "start_at": T0}), 201)


@pytest.fixture
def rx(client, patient, encounter) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/prescriptions", json={
        "encounter_id": encounter["id"], "prescriber_name": "Dr. Njoroge", "prescribed_at": "2026-05-05T09:20:00Z",
        "notes": "Review in 1 week", "items": [AMOXICILLIN]}), 201)


def act(client, rx, action, body=None):
    return client.post(f"/api/prescriptions/{rx['id']}/{action}", json=body)


def test_create_prescription(client, rx, patient, encounter):
    assert re.fullmatch(r"RX-\d{6}", rx["prescription_number"])
    assert rx["status"] == "DRAFT" and rx["patient_id"] == patient["id"] and rx["encounter_id"] == encounter["id"]
    [item] = rx["items"]
    assert item["line_number"] == 1 and item["dose_value"] == 500 and item["route"] == "ORAL"
    assert item["frequency"] == "TID" and item["duration_value"] == 7 and item["code"] == "308182"
    assert ok(client.get(f"/api/prescriptions/{rx['id']}")) == rx


def test_lifecycle_draft_active_hold_resume_complete(client, rx):
    added = ok(client.post(f"/api/prescriptions/{rx['id']}/items", json=PARACETAMOL))
    assert [i["line_number"] for i in added["items"]] == [1, 2]
    ok(client.patch(f"/api/prescriptions/{rx['id']}", json={"notes": "Updated notes"}))

    active = ok(act(client, rx, "activate"))
    assert active["status"] == "ACTIVE" and active["activated_at"] >= active["prescribed_at"]
    held = ok(act(client, rx, "hold"))
    assert held["status"] == "ON_HOLD"
    resumed = ok(act(client, rx, "resume"))
    assert resumed["status"] == "ACTIVE" and resumed["activated_at"] == active["activated_at"]
    done = ok(act(client, rx, "complete"))
    assert done["status"] == "COMPLETED" and done["completed_at"] >= done["activated_at"]
    assert done["notes"] == "Updated notes" and len(done["items"]) == 2


@pytest.mark.parametrize("reach", [[], ["activate"], ["activate", "hold"]])
def test_cancel_allowed_until_completed(client, rx, reach):
    for step in reach:
        ok(act(client, rx, step))
    cancelled = ok(act(client, rx, "cancel", {"reason": "Allergy discovered"}))
    assert cancelled["status"] == "CANCELLED" and cancelled["cancellation_reason"] == "Allergy discovered"


@pytest.mark.parametrize(
    ("reach", "action", "body"),
    [
        ([], "hold", None),
        ([], "resume", None),
        ([], "complete", None),
        (["activate"], "activate", None),
        (["activate"], "resume", None),
        (["activate", "hold"], "complete", None),
        (["activate", "hold"], "hold", None),
        (["activate", "complete"], "cancel", {"reason": "x"}),
        (["activate", "complete"], "activate", None),
        (["cancel"], "activate", None),
        (["cancel"], "cancel", {"reason": "x"}),
    ],
)
def test_invalid_prescription_transitions_are_409(client, rx, reach, action, body):
    for step in reach:
        ok(act(client, rx, step, {"reason": "setup"} if step == "cancel" else None))
    before = ok(client.get(f"/api/prescriptions/{rx['id']}"))
    assert act(client, rx, action, body).status_code == 409
    assert ok(client.get(f"/api/prescriptions/{rx['id']}")) == before


@pytest.mark.parametrize("reach", [["activate"], ["activate", "hold"], ["cancel"]])
def test_items_and_notes_only_editable_in_draft(client, rx, reach):
    for step in reach:
        ok(act(client, rx, step, {"reason": "x"} if step == "cancel" else None))
    assert client.post(f"/api/prescriptions/{rx['id']}/items", json=PARACETAMOL).status_code == 409
    assert client.patch(f"/api/prescriptions/{rx['id']}", json={"notes": "x"}).status_code == 409


def test_activation_requires_active_patient(client, rx, patient):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Transferred"}))
    assert act(client, rx, "activate").status_code == 409
    assert ok(act(client, rx, "cancel", {"reason": "Patient transferred"}))["status"] == "CANCELLED"


@pytest.mark.parametrize(
    "bad_item",
    [
        {**AMOXICILLIN, "dose_value": 0},
        {**AMOXICILLIN, "dose_value": -1},
        {**AMOXICILLIN, "route": "MOUTH"},
        {**AMOXICILLIN, "frequency": "THREE_TIMES"},
        {**AMOXICILLIN, "duration_unit": None},
        {**AMOXICILLIN, "duration_value": 0},
        {**AMOXICILLIN, "quantity": -21},
        {**PARACETAMOL, "instructions": None},
        {k: v for k, v in AMOXICILLIN.items() if k != "medicine_name"},
    ],
)
def test_invalid_items_are_422(client, patient, encounter, bad_item):
    body = {"encounter_id": encounter["id"], "prescriber_name": "Dr. N", "items": [bad_item]}
    assert client.post(f"/api/patients/{patient['id']}/prescriptions", json=body).status_code == 422
    assert ok(client.get(f"/api/patients/{patient['id']}/prescriptions"))["total"] == 0


def test_invalid_prescriptions_are_422(client, patient, encounter, patient_payload):
    base = {"encounter_id": encounter["id"], "prescriber_name": "Dr. N", "items": [AMOXICILLIN]}
    url = f"/api/patients/{patient['id']}/prescriptions"
    assert client.post(url, json={**base, "items": []}).status_code == 422
    assert client.post(url, json={**base, "prescriber_name": " "}).status_code == 422
    assert client.post(url, json={**base, "prescribed_at": "2026-05-05T08:00:00Z"}).status_code == 422  # before encounter
    assert client.post(url, json={**base, "encounter_id": str(uuid.uuid4())}).status_code == 422
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Other")), 201)
    assert client.post(f"/api/patients/{other['id']}/prescriptions", json=base).status_code == 422


def test_cancelled_encounter_cannot_get_prescriptions(client, patient, encounter):
    ok(client.post(f"/api/encounters/{encounter['id']}/cancel", json={"reason": "Wrong patient"}))
    body = {"encounter_id": encounter["id"], "prescriber_name": "Dr. N", "items": [AMOXICILLIN]}
    assert client.post(f"/api/patients/{patient['id']}/prescriptions", json=body).status_code == 409


def test_list_prescriptions(client, patient, encounter, rx):
    second = ok(client.post(f"/api/patients/{patient['id']}/prescriptions", json={
        "encounter_id": encounter["id"], "prescriber_name": "Dr. N", "prescribed_at": "2026-05-05T09:40:00Z",
        "items": [PARACETAMOL]}), 201)
    ok(act(client, second, "activate"))
    body = ok(client.get(f"/api/patients/{patient['id']}/prescriptions"))
    assert [p["id"] for p in body["items"]] == [second["id"], rx["id"]]
    assert ok(client.get(f"/api/patients/{patient['id']}/prescriptions", params={"status": "ACTIVE"}))["total"] == 1
    assert ok(client.get(f"/api/patients/{patient['id']}/prescriptions",
                         params={"encounter_id": encounter["id"]}))["total"] == 2


def test_missing_resources(client):
    assert client.get(f"/api/prescriptions/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/prescriptions/xyz").status_code == 422
    assert client.post(f"/api/prescriptions/{uuid.uuid4()}/activate").status_code == 404
    assert client.post(f"/api/prescriptions/{uuid.uuid4()}/items", json=PARACETAMOL).status_code == 404
    assert client.get(f"/api/patients/{uuid.uuid4()}/prescriptions").status_code == 404
    assert client.delete(f"/api/prescriptions/{uuid.uuid4()}").status_code == 405


def test_no_prescriptions_for_inactive_patient(client, patient, encounter):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Deceased"}))
    body = {"encounter_id": encounter["id"], "prescriber_name": "Dr. N", "items": [AMOXICILLIN]}
    assert client.post(f"/api/patients/{patient['id']}/prescriptions", json=body).status_code == 409
