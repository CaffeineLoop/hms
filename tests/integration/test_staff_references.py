"""Stage 4: staff references on Stage 2/3 clinical records (replacing temporary free-text names)."""

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

T0 = "2026-07-01T08:00:00Z"


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1980-01-01")), 201)


@pytest.fixture
def team(make_department, make_staff) -> dict:
    lab = make_department(name="Laboratory")
    medicine = make_department(name="Medicine")
    return {
        "doctor": make_staff(medicine, first_name="Amani", last_name="Njoroge", designation="DOCTOR"),
        "nurse": make_staff(medicine, first_name="Beatrice", last_name="Wafula", designation="NURSE"),
        "tech": make_staff(lab, first_name="Collins", last_name="Kiplagat", designation="LAB_TECHNICIAN"),
        "pathologist": make_staff(lab, first_name="Dorcas", last_name="Achieng", designation="DOCTOR"),
    }


@pytest.fixture
def encounter(client, patient, team) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/encounters", json={
        "encounter_type": "OPD", "reason": "Fever", "start_at": T0, "attending_staff_id": team["doctor"]["id"]}), 201)


def test_encounter_attending_clinician(encounter, team):
    assert encounter["attending_staff_id"] == team["doctor"]["id"]


def test_clinical_note_author_from_staff(client, patient, encounter, team):
    note = ok(client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "PROGRESS", "author_staff_id": team["doctor"]["id"],
        "content": "Febrile, alert."}), 201)
    assert note["author_staff_id"] == team["doctor"]["id"] and note["author_name"] == "Amani Njoroge"


def test_legacy_free_text_still_accepted(client, patient, encounter):
    note = ok(client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "PROGRESS", "author_name": "Dr. Visiting Consultant",
        "content": "x"}), 201)
    assert note["author_staff_id"] is None and note["author_name"] == "Dr. Visiting Consultant"


def test_name_snapshot_survives_staff_rename(client, patient, encounter, team):
    note = ok(client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "PROGRESS", "author_staff_id": team["doctor"]["id"],
        "content": "x"}), 201)
    ok(client.patch(f"/api/staff/{team['doctor']['id']}", json={"last_name": "Njoroge-Mwangi"}))
    assert ok(client.get(f"/api/clinical-notes/{note['id']}"))["author_name"] == "Amani Njoroge"


def test_full_lab_workflow_with_staff(client, patient, encounter, team):
    order = ok(client.post(f"/api/patients/{patient['id']}/lab-orders", json={
        "encounter_id": encounter["id"], "test_code": "malaria_rdt", "test_name": "Malaria RDT",
        "ordered_by_staff_id": team["doctor"]["id"], "ordered_at": "2026-07-01T08:05:00Z"}), 201)
    assert (order["ordered_by_staff_id"], order["ordered_by"]) == (team["doctor"]["id"], "Amani Njoroge")
    sample = ok(client.post(f"/api/lab-orders/{order['id']}/samples", json={
        "specimen_type": "BLOOD", "collected_by_staff_id": team["nurse"]["id"],
        "collected_at": "2026-07-01T08:10:00Z"}), 201)
    assert (sample["collected_by_staff_id"], sample["collected_by"]) == (team["nurse"]["id"], "Beatrice Wafula")
    ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
    entered = ok(client.post(f"/api/lab-orders/{order['id']}/results", json={
        "entered_by_staff_id": team["tech"]["id"],
        "results": [{"analyte_code": "p_falciparum", "analyte_name": "P. falciparum antigen", "value_text": "Positive",
                     "resulted_at": "2026-07-01T08:30:00Z"}]}))
    result = entered["results"][0]
    assert (result["entered_by_staff_id"], result["entered_by"]) == (team["tech"]["id"], "Collins Kiplagat")
    # Correction by another person switches the reference (and can fall back to legacy free text).
    corrected = ok(client.patch(f"/api/lab-results/{result['id']}", json={
        "value_text": "Positive (2+)", "entered_by": "Relief technician"}))
    assert corrected["entered_by_staff_id"] is None and corrected["entered_by"] == "Relief technician"
    verified = ok(client.post(f"/api/lab-orders/{order['id']}/verify", json={"verified_by_staff_id": team["pathologist"]["id"]}))
    assert (verified["verified_by_staff_id"], verified["verified_by"]) == (team["pathologist"]["id"], "Dorcas Achieng")


def test_report_people_from_staff(client, patient, encounter, team):
    report = ok(client.post(f"/api/patients/{patient['id']}/reports", json={
        "report_type": "CONSULTATION", "title": "Cardiology opinion", "encounter_id": encounter["id"],
        "author_staff_id": team["pathologist"]["id"], "requested_by_staff_id": team["doctor"]["id"],
        "effective_at": "2026-07-01T09:00:00Z", "content": "No structural disease."}), 201)
    assert report["author_name"] == "Dorcas Achieng" and report["requested_by"] == "Amani Njoroge"
    verified = ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by_staff_id": team["doctor"]["id"]}))
    assert verified["verified_by_staff_id"] == team["doctor"]["id"] and verified["verified_by"] == "Amani Njoroge"


def test_prescriber_from_staff(client, patient, encounter, team):
    rx = ok(client.post(f"/api/patients/{patient['id']}/prescriptions", json={
        "encounter_id": encounter["id"], "prescriber_staff_id": team["doctor"]["id"],
        "prescribed_at": "2026-07-01T09:10:00Z",
        "items": [{"medicine_name": "Paracetamol 500 mg tablet", "dose_value": 1000, "dose_unit": "mg",
                   "route": "ORAL", "frequency": "QID", "duration_value": 3, "duration_unit": "DAYS"}]}), 201)
    assert (rx["prescriber_staff_id"], rx["prescriber_name"]) == (team["doctor"]["id"], "Amani Njoroge")


PEOPLE = [
    ("clinical-notes", {"note_type": "PROGRESS", "content": "x"}, "author_staff_id", "author_name"),
    ("lab-orders", {"test_code": "x", "test_name": "X"}, "ordered_by_staff_id", "ordered_by"),
    ("prescriptions", {"items": [{"medicine_name": "X", "dose_value": 1, "dose_unit": "mg", "route": "ORAL",
                                  "frequency": "OD"}]}, "prescriber_staff_id", "prescriber_name"),
    ("reports", {"report_type": "OTHER", "title": "x"}, "author_staff_id", "author_name"),
]


@pytest.mark.parametrize(("collection", "body", "staff_field", "name_field"), PEOPLE)
def test_invalid_staff_references(client, patient, encounter, team, collection, body, staff_field, name_field):
    url = f"/api/patients/{patient['id']}/{collection}"
    body = {**body, "encounter_id": encounter["id"]}
    unknown = client.post(url, json={**body, staff_field: str(uuid.uuid4())})
    assert unknown.status_code == 422 and unknown.json()["detail"][0]["loc"] == ["body", staff_field]
    both = client.post(url, json={**body, staff_field: team["doctor"]["id"], name_field: "Dr. X"})
    assert both.status_code == 422
    assert client.post(url, json=body).status_code == 422  # neither
    assert client.post(url, json={**body, staff_field: "not-a-uuid"}).status_code == 422
    ok(client.post(f"/api/staff/{team['nurse']['id']}/deactivate"))
    inactive = client.post(url, json={**body, staff_field: team["nurse"]["id"]})
    assert inactive.status_code == 409 and "inactive" in inactive.json()["detail"]


def test_unknown_attending_clinician_is_422(client, patient):
    response = client.post(f"/api/patients/{patient['id']}/encounters", json={
        "encounter_type": "OPD", "reason": "x", "attending_staff_id": str(uuid.uuid4())})
    assert response.status_code == 422


def test_staff_referenced_by_records_cannot_be_deleted_at_db_level(client, patient, encounter, team, test_engine):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="fk_encounters_attending_staff_id_staff"):
        with test_engine.begin() as connection:
            connection.execute(text("DELETE FROM staff WHERE id = :id"), {"id": team["doctor"]["id"]})
