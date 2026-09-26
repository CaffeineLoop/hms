"""Stage 2 clinical-record API end-to-end against the isolated test database (hms_test)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

T0 = "2026-01-10T09:00:00Z"


def at(minutes: int, base: str = T0) -> str:
    start = datetime.fromisoformat(base.replace("Z", "+00:00"))
    return (start + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1980-05-05")), 201)


@pytest.fixture
def other_patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(first_name="Other", date_of_birth="1990-01-01")), 201)


@pytest.fixture
def encounter(client, patient) -> dict:
    """An IN_PROGRESS OPD encounter that started at T0."""
    return ok(client.post(f"/api/patients/{patient['id']}/encounters",
                          json={"encounter_type": "OPD", "reason": "Fever and cough", "start_at": T0}), 201)


def url(patient: dict, collection: str) -> str:
    return f"/api/patients/{patient['id']}/{collection}"


# --- encounters: lifecycle ------------------------------------------------------------


def test_create_encounter_defaults(client, patient):
    response = client.post(url(patient, "encounters"), json={"encounter_type": "EMERGENCY", "reason": "Chest pain"})
    body = ok(response, 201)
    assert response.headers["Location"] == f"/api/encounters/{body['id']}"
    assert body["status"] == "IN_PROGRESS" and body["patient_id"] == patient["id"]
    assert body["end_at"] is None and body["start_at"].endswith("Z")
    started = datetime.fromisoformat(body["start_at"])
    assert abs(started - datetime.now(UTC)) < timedelta(minutes=1)


def test_encounter_full_lifecycle_planned_to_finished(client, patient):
    planned_for = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    e = ok(client.post(url(patient, "encounters"),
                       json={"encounter_type": "FOLLOW_UP", "reason": "Review", "status": "PLANNED",
                             "start_at": planned_for}), 201)
    assert e["status"] == "PLANNED"

    started = ok(client.post(f"/api/encounters/{e['id']}/start"))
    assert started["status"] == "IN_PROGRESS"
    assert datetime.fromisoformat(started["start_at"]) < datetime.fromisoformat(planned_for)  # actual start

    finished = ok(client.post(f"/api/encounters/{e['id']}/finish", json={"summary": "Improving"}))
    assert finished["status"] == "FINISHED" and finished["summary"] == "Improving"
    assert finished["end_at"] >= finished["start_at"]
    assert ok(client.get(f"/api/encounters/{e['id']}")) == finished


def test_cancel_encounter(client, encounter):
    cancelled = ok(client.post(f"/api/encounters/{encounter['id']}/cancel", json={"reason": "Registered in error"}))
    assert cancelled["status"] == "CANCELLED" and cancelled["cancellation_reason"] == "Registered in error"


def test_historical_finished_encounter(client, patient):
    e = ok(client.post(url(patient, "encounters"), json={
        "encounter_type": "INPATIENT", "reason": "Pneumonia", "status": "FINISHED",
        "start_at": "2025-05-01T08:00:00Z", "end_at": "2025-05-04T12:00:00Z", "summary": "Discharged home"}), 201)
    assert e["status"] == "FINISHED"


@pytest.mark.parametrize(
    ("setup", "action", "body"),
    [
        ([], "start", None),                                     # IN_PROGRESS -> start
        (["finish"], "finish", None),                            # finish twice
        (["finish"], "cancel", {"reason": "x"}),                 # FINISHED is terminal
        (["finish"], "start", None),
        (["cancel"], "finish", None),                            # CANCELLED is terminal
        (["cancel"], "cancel", {"reason": "x"}),
    ],
)
def test_invalid_encounter_transitions_are_409(client, encounter, setup, action, body):
    for step in setup:
        ok(client.post(f"/api/encounters/{encounter['id']}/{step}", json={"reason": "setup"} if step == "cancel" else None))
    before = ok(client.get(f"/api/encounters/{encounter['id']}"))
    response = client.post(f"/api/encounters/{encounter['id']}/{action}", json=body)
    assert response.status_code == 409
    assert ok(client.get(f"/api/encounters/{encounter['id']}")) == before


def test_planned_encounter_cannot_be_finished_directly(client, patient):
    e = ok(client.post(url(patient, "encounters"), json={
        "encounter_type": "OPD", "reason": "Booked", "status": "PLANNED", "start_at": T0}), 201)
    assert client.post(f"/api/encounters/{e['id']}/finish").status_code == 409


def test_finish_before_start_is_422(client, encounter):
    response = client.post(f"/api/encounters/{encounter['id']}/finish", json={"end_at": at(-60)})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "end_at"]


def test_cancel_requires_reason(client, encounter):
    assert client.post(f"/api/encounters/{encounter['id']}/cancel", json={}).status_code == 422
    assert client.post(f"/api/encounters/{encounter['id']}/cancel").status_code == 422


def test_encounter_before_birth_is_422(client, patient):
    response = client.post(url(patient, "encounters"),
                           json={"encounter_type": "OPD", "reason": "x", "start_at": "1979-01-01T00:00:00Z"})
    assert response.status_code == 422
    assert "date of birth" in response.json()["detail"][0]["msg"]


@pytest.mark.parametrize(
    "body",
    [
        {"encounter_type": "OPD", "reason": "x", "start_at": "2026-01-10T09:00:00"},  # naive
        {"encounter_type": "OPD", "reason": "x", "start_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()},
        {"encounter_type": "WALK_IN", "reason": "x"},
        {"encounter_type": "OPD"},
    ],
)
def test_invalid_encounter_input_is_422(client, patient, body):
    assert client.post(url(patient, "encounters"), json=body).status_code == 422


def test_list_encounters_filters_and_order(client, patient):
    for i, kind in enumerate(["OPD", "EMERGENCY", "OPD"]):
        ok(client.post(url(patient, "encounters"), json={"encounter_type": kind, "reason": f"v{i}", "start_at": at(i * 60)}), 201)
    body = ok(client.get(url(patient, "encounters")))
    assert body["total"] == 3 and [e["reason"] for e in body["items"]] == ["v2", "v1", "v0"]  # newest first
    assert ok(client.get(url(patient, "encounters"), params={"encounter_type": "OPD"}))["total"] == 2
    assert ok(client.get(url(patient, "encounters"), params={"status": "FINISHED"}))["total"] == 0
    page = ok(client.get(url(patient, "encounters"), params={"limit": 1, "offset": 1}))
    assert [e["reason"] for e in page["items"]] == ["v1"]


def test_encounters_for_inactive_patient(client, patient, encounter):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Moved"}))
    response = client.post(url(patient, "encounters"), json={"encounter_type": "OPD", "reason": "x"})
    assert response.status_code == 409 and "inactive" in response.json()["detail"]
    # Existing records stay readable and an open encounter can still be closed.
    assert ok(client.get(url(patient, "encounters")))["total"] == 1
    assert ok(client.post(f"/api/encounters/{encounter['id']}/finish"))["status"] == "FINISHED"


# --- patient relationship / missing / invalid ids ---------------------------------------

COLLECTIONS = ["encounters", "observations", "conditions", "allergies", "clinical-notes", "timeline"]
ITEMS = ["encounters", "observations", "conditions", "allergies", "clinical-notes"]


@pytest.mark.parametrize("collection", COLLECTIONS)
def test_missing_patient_is_404(client, collection):
    missing = uuid.uuid4()
    response = client.get(f"/api/patients/{missing}/{collection}")
    assert response.status_code == 404
    assert response.json() == {"detail": f"Patient {missing} not found."}


@pytest.mark.parametrize("collection", ITEMS)
def test_create_for_missing_patient_is_404(client, collection):
    assert client.post(f"/api/patients/{uuid.uuid4()}/{collection}", json={}).status_code in (404, 422)
    minimal = {
        "encounters": {"encounter_type": "OPD", "reason": "x"},
        "observations": {"code": "heart_rate", "value_numeric": 70, "unit": "/min", "effective_at": T0},
        "conditions": {"name": "Asthma"},
        "allergies": {"substance": "Latex"},
        "clinical-notes": {"encounter_id": str(uuid.uuid4()), "note_type": "OTHER", "author_name": "A", "content": "c"},
    }[collection]
    assert client.post(f"/api/patients/{uuid.uuid4()}/{collection}", json=minimal).status_code == 404


@pytest.mark.parametrize("collection", ITEMS)
def test_missing_record_is_404_and_invalid_uuid_is_422(client, collection):
    assert client.get(f"/api/{collection}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/{collection}/not-a-uuid").status_code == 422
    assert client.get(f"/api/patients/not-a-uuid/{collection}").status_code == 422


@pytest.mark.parametrize("collection", ITEMS)
def test_no_delete_endpoints(client, collection):
    assert client.delete(f"/api/{collection}/{uuid.uuid4()}").status_code == 405


def test_record_cannot_use_another_patients_encounter(client, patient, other_patient, encounter):
    response = client.post(url(other_patient, "observations"), json={
        "code": "heart_rate", "value_numeric": 70, "unit": "/min", "effective_at": at(5),
        "encounter_id": encounter["id"]})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "encounter_id"]


def test_unknown_encounter_is_422(client, patient):
    response = client.post(url(patient, "conditions"), json={"name": "Asthma", "encounter_id": str(uuid.uuid4())})
    assert response.status_code == 422


def test_records_cannot_attach_to_planned_or_cancelled_encounters(client, patient, encounter):
    planned = ok(client.post(url(patient, "encounters"), json={
        "encounter_type": "OPD", "reason": "Booked", "status": "PLANNED", "start_at": T0}), 201)
    ok(client.post(f"/api/encounters/{encounter['id']}/cancel", json={"reason": "Error"}))
    for e in (planned, encounter):
        response = client.post(url(patient, "clinical-notes"), json={
            "encounter_id": e["id"], "note_type": "PROGRESS", "author_name": "Dr. A", "content": "x", "authored_at": at(10)})
        assert response.status_code == 409


def test_records_can_attach_to_finished_encounter(client, patient, encounter):
    ok(client.post(f"/api/encounters/{encounter['id']}/finish", json={"end_at": at(30)}))
    ok(client.post(url(patient, "clinical-notes"), json={
        "encounter_id": encounter["id"], "note_type": "DISCHARGE_SUMMARY", "author_name": "Dr. A",
        "content": "Late entry", "authored_at": at(120)}), 201)


def test_no_new_records_for_inactive_patient(client, patient):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Deceased"}))
    assert client.post(url(patient, "allergies"), json={"substance": "Latex"}).status_code == 409
    assert client.post(url(patient, "conditions"), json={"name": "Asthma"}).status_code == 409


def test_patient_record_unchanged_by_clinical_records(client, patient, encounter):
    ok(client.post(url(patient, "conditions"), json={"name": "Asthma"}), 201)
    assert ok(client.get(f"/api/patients/{patient['id']}")) == patient


# --- observations ---------------------------------------------------------------------------


def test_record_vitals_set(client, patient, encounter):
    vitals = [
        ("body_temperature", 38.4, "Cel"), ("heart_rate", 104, "/min"), ("respiratory_rate", 22, "/min"),
        ("oxygen_saturation", 95, "%"), ("systolic_blood_pressure", 128, "mm[Hg]"),
        ("diastolic_blood_pressure", 84, "mm[Hg]"), ("body_weight", 71.2, "kg"), ("blood_glucose", 110, "mg/dL"),
    ]
    for code, value, unit in vitals:
        body = ok(client.post(url(patient, "observations"), json={
            "code": code, "value_numeric": value, "unit": unit, "effective_at": at(5), "encounter_id": encounter["id"]}), 201)
        assert body["value_numeric"] == value and body["unit"] == unit
        assert body["code_system"] == "http://loinc.org" and body["system_code"]
    listed = ok(client.get(url(patient, "observations"), params={"encounter_id": encounter["id"], "limit": 100}))
    assert listed["total"] == len(vitals)
    bp = ok(client.get(url(patient, "observations"), params={"code": "systolic_blood_pressure"}))
    assert [o["value_numeric"] for o in bp["items"]] == [128]


def test_observation_without_encounter_and_text_value(client, patient):
    body = ok(client.post(url(patient, "observations"), json={
        "code": "smoking_status", "display": "Tobacco smoking status", "value_text": "Never smoker",
        "code_system": "http://loinc.org", "system_code": "72166-2", "effective_at": T0}), 201)
    assert body["encounter_id"] is None and body["value_text"] == "Never smoker" and body["unit"] is None
    assert ok(client.get(f"/api/observations/{body['id']}")) == body


@pytest.mark.parametrize(
    "overrides",
    [
        {"unit": "bpm"},
        {"value_numeric": 999},
        {"effective_at": "2026-01-10T09:00:00"},
        {"effective_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        {"effective_at": "1975-01-01T00:00:00Z"},  # before the patient's birth
    ],
)
def test_invalid_observation_is_422(client, patient, overrides):
    body = {"code": "heart_rate", "value_numeric": 70, "unit": "/min", "effective_at": T0, **overrides}
    assert client.post(url(patient, "observations"), json=body).status_code == 422


def test_observation_before_encounter_start_is_422(client, patient, encounter):
    response = client.post(url(patient, "observations"), json={
        "code": "heart_rate", "value_numeric": 70, "unit": "/min", "effective_at": at(-30),
        "encounter_id": encounter["id"]})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "effective_at"]


# --- conditions ---------------------------------------------------------------------------------


def test_condition_lifecycle(client, patient, encounter):
    c = ok(client.post(url(patient, "conditions"), json={
        "name": "Community-acquired pneumonia", "code_system": "http://snomed.info/sct", "code": "385093006",
        "status": "SUSPECTED", "onset_at": at(-3 * 24 * 60), "recorded_at": at(20),
        "encounter_id": encounter["id"], "notes": "Crackles right base"}), 201)
    assert c["status"] == "SUSPECTED" and c["onset_at"] < c["recorded_at"]

    c = ok(client.patch(f"/api/conditions/{c['id']}", json={"status": "ACTIVE"}))
    assert c["status"] == "ACTIVE"
    c = ok(client.patch(f"/api/conditions/{c['id']}", json={"status": "RESOLVED", "resolved_at": at(7 * 24 * 60)}))
    assert c["status"] == "RESOLVED" and c["resolved_at"]
    c = ok(client.patch(f"/api/conditions/{c['id']}", json={"status": "ACTIVE", "notes": "Recurred"}))
    assert c["status"] == "ACTIVE" and c["resolved_at"] is None and c["notes"] == "Recurred"
    assert ok(client.get(f"/api/conditions/{c['id']}")) == c


def test_condition_recorded_at_defaults_to_now(client, patient):
    c = ok(client.post(url(patient, "conditions"), json={"name": "Type 2 diabetes mellitus"}), 201)
    assert abs(datetime.fromisoformat(c["recorded_at"]) - datetime.now(UTC)) < timedelta(minutes=1)


@pytest.mark.parametrize(
    ("initial", "patch"),
    [
        ("ACTIVE", {"status": "SUSPECTED"}),
        ("ACTIVE", {"status": "ACTIVE"}),
        ("ACTIVE", {"status": "HISTORICAL"}),
        ("HISTORICAL", {"status": "RESOLVED"}),
    ],
)
def test_invalid_condition_transitions_are_409(client, patient, initial, patch):
    c = ok(client.post(url(patient, "conditions"), json={"name": "Asthma", "status": initial}), 201)
    assert client.patch(f"/api/conditions/{c['id']}", json=patch).status_code == 409


def test_condition_update_validation(client, patient):
    c = ok(client.post(url(patient, "conditions"), json={"name": "Asthma", "onset_at": "2020-01-01T00:00:00Z"}), 201)
    assert client.patch(f"/api/conditions/{c['id']}", json={"resolved_at": T0}).status_code == 422  # still ACTIVE
    response = client.patch(f"/api/conditions/{c['id']}", json={"status": "RESOLVED", "resolved_at": "2019-01-01T00:00:00Z"})
    assert response.status_code == 422  # before onset
    assert client.patch(f"/api/conditions/{c['id']}", json={}).status_code == 422
    assert client.patch(f"/api/conditions/{uuid.uuid4()}", json={"notes": "x"}).status_code == 404


def test_list_conditions_by_status(client, patient):
    ok(client.post(url(patient, "conditions"), json={"name": "Asthma"}), 201)
    ok(client.post(url(patient, "conditions"), json={"name": "Measles", "status": "HISTORICAL"}), 201)
    assert ok(client.get(url(patient, "conditions"), params={"status": "HISTORICAL"}))["total"] == 1
    assert ok(client.get(url(patient, "conditions")))["total"] == 2


# --- allergies -----------------------------------------------------------------------------------


def test_allergy_create_update(client, patient):
    a = ok(client.post(url(patient, "allergies"), json={
        "substance": "Penicillin V", "code_system": "http://www.nlm.nih.gov/research/umls/rxnorm", "code": "7984",
        "category": "MEDICATION", "reaction": "Urticaria", "severity": "MODERATE", "recorded_at": T0}), 201)
    assert a["status"] == "ACTIVE"
    a = ok(client.patch(f"/api/allergies/{a['id']}", json={"severity": "SEVERE", "reaction": "Anaphylaxis"}))
    assert (a["severity"], a["reaction"]) == ("SEVERE", "Anaphylaxis")
    a = ok(client.patch(f"/api/allergies/{a['id']}", json={"status": "INACTIVE"}))
    assert a["status"] == "INACTIVE"
    assert ok(client.get(f"/api/allergies/{a['id']}")) == a


def test_duplicate_active_allergy_is_409(client, patient):
    ok(client.post(url(patient, "allergies"), json={"substance": "Peanut"}), 201)
    response = client.post(url(patient, "allergies"), json={"substance": "PEANUT"})
    assert response.status_code == 409 and "already has an active allergy" in response.json()["detail"]


def test_allergy_reactivation_conflict(client, patient):
    old = ok(client.post(url(patient, "allergies"), json={"substance": "Latex", "status": "INACTIVE"}), 201)
    ok(client.post(url(patient, "allergies"), json={"substance": "latex"}), 201)
    assert client.patch(f"/api/allergies/{old['id']}", json={"status": "ACTIVE"}).status_code == 409


def test_invalid_allergy_transitions(client, patient):
    a = ok(client.post(url(patient, "allergies"), json={"substance": "Dust", "status": "RESOLVED"}), 201)
    assert client.patch(f"/api/allergies/{a['id']}", json={"status": "INACTIVE"}).status_code == 409
    assert client.patch(f"/api/allergies/{a['id']}", json={"status": "RESOLVED"}).status_code == 409


def test_allergy_list_and_other_patient_isolation(client, patient, other_patient):
    ok(client.post(url(patient, "allergies"), json={"substance": "Peanut"}), 201)
    ok(client.post(url(other_patient, "allergies"), json={"substance": "Peanut"}), 201)  # per patient
    assert ok(client.get(url(patient, "allergies")))["total"] == 1
    assert ok(client.get(url(other_patient, "allergies"), params={"status": "ACTIVE"}))["total"] == 1


# --- clinical notes -------------------------------------------------------------------------------


def test_clinical_note(client, patient, encounter):
    n = ok(client.post(url(patient, "clinical-notes"), json={
        "encounter_id": encounter["id"], "note_type": "HISTORY_AND_PHYSICAL", "author_name": "Dr. Achieng Otieno",
        "content": "3-day history of fever.\nExam: crackles R base.", "authored_at": at(15)}), 201)
    assert n["content"].startswith("3-day") and n["authored_at"] == at(15).replace("Z", "Z")
    assert ok(client.get(f"/api/clinical-notes/{n['id']}")) == n
    assert ok(client.get(url(patient, "clinical-notes"), params={"note_type": "PROGRESS"}))["total"] == 0
    assert ok(client.get(url(patient, "clinical-notes"), params={"encounter_id": encounter["id"]}))["total"] == 1


def test_notes_are_append_only(client, patient, encounter):
    n = ok(client.post(url(patient, "clinical-notes"), json={
        "encounter_id": encounter["id"], "note_type": "PROGRESS", "author_name": "A", "content": "x"}), 201)
    assert client.patch(f"/api/clinical-notes/{n['id']}", json={"content": "y"}).status_code == 405


def test_note_requires_encounter_and_valid_times(client, patient, encounter):
    base = {"note_type": "PROGRESS", "author_name": "A", "content": "x"}
    assert client.post(url(patient, "clinical-notes"), json=base).status_code == 422
    early = {**base, "encounter_id": encounter["id"], "authored_at": at(-5)}
    assert client.post(url(patient, "clinical-notes"), json=early).status_code == 422
