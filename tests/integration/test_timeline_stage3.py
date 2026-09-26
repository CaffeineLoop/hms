"""Timeline integration of laboratory, report and prescription events."""

import json

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

START = "2026-06-01T08:00:00Z"


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1970-01-01")), 201)


@pytest.fixture
def encounter(client, patient) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/encounters",
                          json={"encounter_type": "EMERGENCY", "reason": "Fever", "start_at": START}), 201)


def timeline(client, patient, **params) -> list[dict]:
    return ok(client.get(f"/api/patients/{patient['id']}/timeline", params={"limit": 100, **params}))["items"]


def kinds(events) -> list[str]:
    return [e["event_type"] for e in events]


@pytest.fixture
def lab(client, patient, encounter) -> dict:
    order = ok(client.post(f"/api/patients/{patient['id']}/lab-orders", json={
        "encounter_id": encounter["id"], "test_code": "malaria_smear", "test_name": "Malaria blood smear",
        "ordered_by": "Dr. A", "ordered_at": "2026-06-01T08:10:00Z"}), 201)
    sample = ok(client.post(f"/api/lab-orders/{order['id']}/samples", json={
        "specimen_type": "BLOOD", "collected_by": "Nurse B", "collected_at": "2026-06-01T08:20:00Z"}), 201)
    ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
    ok(client.post(f"/api/lab-orders/{order['id']}/results", json={"entered_by": "Tech C", "results": [
        {"analyte_code": "p_falciparum", "analyte_name": "P. falciparum", "value_text": "Seen (2+)",
         "interpretation": "ABNORMAL", "resulted_at": "2026-06-01T09:00:00Z"},
        {"analyte_code": "parasite_density", "analyte_name": "Parasite density", "value_numeric": 12000,
         "unit": "/uL", "reference_high": 0, "resulted_at": "2026-06-01T09:00:00Z"}]}))
    return {"order": order, "sample": sample}


def test_lab_events_before_release_hide_results(client, patient, lab):
    events = timeline(client, patient, order="asc")
    assert kinds(events) == ["encounter", "lab_order", "lab_sample"]
    order_event = events[1]
    assert order_event["title"] == f"Lab order {lab['order']['order_number']}: Malaria blood smear"
    assert order_event["status"] == "RESULT_ENTERED" and order_event["occurred_at"] == "2026-06-01T08:10:00Z"
    assert "results" not in order_event["data"] and "samples" not in order_event["data"]
    serialized = json.dumps(events)
    assert "12000" not in serialized and "Seen (2+)" not in serialized  # unverified values never leak
    sample_event = events[2]
    assert sample_event["encounter_id"] == lab["order"]["encounter_id"]
    assert sample_event["title"].startswith(f"Sample {lab['sample']['accession_number']} collected (Blood)")


def test_results_appear_once_released(client, patient, lab):
    order_id = lab["order"]["id"]
    ok(client.post(f"/api/lab-orders/{order_id}/verify", json={"verified_by": "Dr. Lab"}))
    assert "lab_result" not in kinds(timeline(client, patient))  # verified but not released
    ok(client.post(f"/api/lab-orders/{order_id}/release"))
    events = timeline(client, patient, order="asc")
    assert kinds(events) == ["encounter", "lab_order", "lab_sample", "lab_result", "lab_result"]
    results = [e for e in events if e["event_type"] == "lab_result"]
    # Same instant, same type, same transaction (identical created_at): the final tie-breaker is the id.
    assert [e["record_id"] for e in results] == sorted(e["record_id"] for e in results)
    assert sorted(e["title"] for e in results) == ["P. falciparum: Seen (2+) [ABNORMAL]",
                                                   "Parasite density: 12000 /uL [HIGH]"]
    assert timeline(client, patient, order="asc") == events  # repeatable
    assert all(e["encounter_id"] == lab["order"]["encounter_id"] for e in results)
    assert next(e for e in results if e["data"]["value_numeric"] is not None)["data"]["value_numeric"] == 12000
    assert events[1]["status"] == "RELEASED"


def test_cancelled_order_stays_visible_without_results(client, patient, lab):
    ok(client.post(f"/api/lab-orders/{lab['order']['id']}/cancel", json={"reason": "Wrong test"}))
    events = timeline(client, patient)
    assert "lab_result" not in kinds(events)
    assert next(e for e in events if e["event_type"] == "lab_order")["status"] == "CANCELLED"


def test_reports_appear_only_when_released(client, patient, encounter):
    report = ok(client.post(f"/api/patients/{patient['id']}/reports", json={
        "report_type": "IMAGING", "title": "Chest X-ray", "author_name": "Dr. R", "encounter_id": encounter["id"],
        "effective_at": "2026-06-01T10:00:00Z", "content": "Clear lungs."}), 201)
    assert "report" not in kinds(timeline(client, patient))
    ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "Dr. S"}))
    assert "report" not in kinds(timeline(client, patient))
    ok(client.post(f"/api/reports/{report['id']}/release"))
    [event] = timeline(client, patient, types="report")
    assert event["title"] == "Imaging report: Chest X-ray" and event["status"] == "RELEASED"
    assert event["occurred_at"] == "2026-06-01T10:00:00Z" and event["data"]["content"] == "Clear lungs."


def test_prescriptions_appear_once_issued(client, patient, encounter):
    rx = ok(client.post(f"/api/patients/{patient['id']}/prescriptions", json={
        "encounter_id": encounter["id"], "prescriber_name": "Dr. P", "prescribed_at": "2026-06-01T09:30:00Z",
        "items": [{"medicine_name": "Artemether-lumefantrine 20/120 mg tablet", "dose_value": 4,
                   "dose_unit": "tablet", "route": "ORAL", "frequency": "BID", "duration_value": 3,
                   "duration_unit": "DAYS", "quantity": 24, "quantity_unit": "tablet"}]}), 201)
    assert "prescription" not in kinds(timeline(client, patient))  # DRAFT is not yet a prescription
    ok(client.post(f"/api/prescriptions/{rx['id']}/activate"))
    [event] = timeline(client, patient, types="prescription")
    assert event["title"] == f"Prescription {rx['prescription_number']}: Artemether-lumefantrine 20/120 mg tablet"
    assert event["status"] == "ACTIVE" and event["encounter_id"] == encounter["id"]
    assert event["data"]["items"][0]["frequency"] == "BID"
    ok(client.post(f"/api/prescriptions/{rx['id']}/cancel", json={"reason": "Vomiting"}))
    assert timeline(client, patient, types="prescription")[0]["status"] == "CANCELLED"


def test_full_timeline_chronology_and_same_instant_ranks(client, patient, encounter, lab):
    """Stage 2 and Stage 3 events interleave chronologically; ties follow the type rank."""
    same = "2026-06-01T09:00:00Z"  # also the lab results' resulted_at
    ok(client.post(f"/api/lab-orders/{lab['order']['id']}/verify", json={"verified_by": "Dr. Lab"}))
    ok(client.post(f"/api/lab-orders/{lab['order']['id']}/release"))
    ok(client.post(f"/api/patients/{patient['id']}/observations", json={
        "code": "body_temperature", "value_numeric": 39.2, "unit": "Cel", "effective_at": same,
        "encounter_id": encounter["id"]}), 201)
    ok(client.post(f"/api/patients/{patient['id']}/clinical-notes", json={
        "encounter_id": encounter["id"], "note_type": "PROGRESS", "author_name": "Dr. A", "content": "Febrile",
        "authored_at": same}), 201)
    report = ok(client.post(f"/api/patients/{patient['id']}/reports", json={
        "report_type": "LABORATORY", "title": "Malaria smear report", "author_name": "Dr. Lab",
        "lab_order_id": lab["order"]["id"], "encounter_id": encounter["id"], "effective_at": same,
        "content": "P. falciparum 2+"}), 201)
    ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "Dr. Lab"}))
    ok(client.post(f"/api/reports/{report['id']}/release"))
    rx = ok(client.post(f"/api/patients/{patient['id']}/prescriptions", json={
        "encounter_id": encounter["id"], "prescriber_name": "Dr. P", "prescribed_at": same,
        "items": [{"medicine_name": "Paracetamol 500 mg tablet", "dose_value": 1000, "dose_unit": "mg",
                   "route": "ORAL", "frequency": "PRN", "instructions": "Fever; max 4 g/day"}]}), 201)
    ok(client.post(f"/api/prescriptions/{rx['id']}/activate"))

    expected = ["encounter", "lab_order", "lab_sample",
                "observation", "clinical_note", "lab_result", "lab_result", "report", "prescription"]
    events = timeline(client, patient, order="asc")
    assert kinds(events) == expected
    times = [e["occurred_at"] for e in events]
    assert times == sorted(times)
    # Descending reverses the instants but keeps the same deterministic tie order at 09:00.
    desc = timeline(client, patient)
    assert kinds(desc)[:6] == ["observation", "clinical_note", "lab_result", "lab_result", "report", "prescription"]
    # Paging over the combined timeline is stable.
    paged = [e["record_id"] for o in range(0, 9, 4) for e in ok(client.get(
        f"/api/patients/{patient['id']}/timeline", params={"order": "asc", "limit": 4, "offset": o}))["items"]]
    assert paged == [e["record_id"] for e in events]
    # Type filters include the new types.
    assert kinds(timeline(client, patient, types=["lab_order", "lab_result"])) == ["lab_result", "lab_result", "lab_order"]


def test_timeline_isolated_per_patient(client, patient, lab, patient_payload):
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Other")), 201)
    assert timeline(client, other) == []
