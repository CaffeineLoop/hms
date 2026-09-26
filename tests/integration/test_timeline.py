"""Patient timeline: derived from the clinical tables, chronological and deterministic."""

import uuid

import pytest
from sqlalchemy import inspect, text

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

T = "2026-02-01T10:00:00Z"  # a single instant shared by several records


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1970-01-01")), 201)


def post(client, patient, collection, body) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/{collection}", json=body), 201)


def timeline(client, patient, **params) -> dict:
    return ok(client.get(f"/api/patients/{patient['id']}/timeline", params=params))


def kinds(body) -> list[str]:
    return [event["event_type"] for event in body["items"]]


@pytest.fixture
def history(client, patient) -> dict:
    """A small but realistic history, created deliberately OUT of chronological order."""
    records = {}
    records["allergy"] = post(client, patient, "allergies",
                              {"substance": "Penicillin", "severity": "SEVERE", "recorded_at": "2024-03-01T08:00:00Z"})
    records["old_visit"] = post(client, patient, "encounters", {
        "encounter_type": "OPD", "reason": "Sore throat", "status": "FINISHED",
        "start_at": "2023-06-01T09:00:00Z", "end_at": "2023-06-01T09:30:00Z"})
    records["visit"] = post(client, patient, "encounters",
                            {"encounter_type": "EMERGENCY", "reason": "Fever", "start_at": "2026-01-15T22:00:00Z"})
    records["temp"] = post(client, patient, "observations", {
        "code": "body_temperature", "value_numeric": 39.1, "unit": "Cel",
        "effective_at": "2026-01-15T22:10:00Z", "encounter_id": records["visit"]["id"]})
    records["note"] = post(client, patient, "clinical-notes", {
        "encounter_id": records["visit"]["id"], "note_type": "PROGRESS", "author_name": "Dr. B",
        "content": "Febrile.", "authored_at": "2026-01-15T22:30:00Z"})
    # Onset (2026-01-12) is earlier than documentation (2026-01-15): the timeline uses onset.
    records["condition"] = post(client, patient, "conditions", {
        "name": "Malaria", "status": "SUSPECTED", "onset_at": "2026-01-12T00:00:00Z",
        "recorded_at": "2026-01-15T22:20:00Z", "encounter_id": records["visit"]["id"]})
    return records


def test_timeline_is_chronological_newest_first(client, patient, history):
    body = timeline(client, patient)
    assert body["total"] == 6 and body["order"] == "desc" and body["patient_id"] == patient["id"]
    assert [e["record_id"] for e in body["items"]] == [
        history[k]["id"] for k in ("note", "temp", "visit", "condition", "allergy", "old_visit")
    ]
    times = [e["occurred_at"] for e in body["items"]]
    assert times == sorted(times, reverse=True)


def test_timeline_ascending(client, patient, history):
    body = timeline(client, patient, order="asc")
    assert [e["record_id"] for e in body["items"]] == [
        history[k]["id"] for k in ("old_visit", "allergy", "condition", "visit", "temp", "note")
    ]


def test_timeline_uses_explicit_clinical_timestamps(client, patient, history):
    events = {e["record_id"]: e for e in timeline(client, patient)["items"]}
    assert events[history["old_visit"]["id"]]["occurred_at"] == "2023-06-01T09:00:00Z"   # start_at
    assert events[history["temp"]["id"]]["occurred_at"] == "2026-01-15T22:10:00Z"        # effective_at
    assert events[history["condition"]["id"]]["occurred_at"] == "2026-01-12T00:00:00Z"   # onset_at
    assert events[history["allergy"]["id"]]["occurred_at"] == "2024-03-01T08:00:00Z"     # recorded_at
    assert events[history["note"]["id"]]["occurred_at"] == "2026-01-15T22:30:00Z"        # authored_at


def test_condition_without_onset_uses_recorded_at(client, patient):
    c = post(client, patient, "conditions", {"name": "Asthma", "recorded_at": "2025-01-01T00:00:00Z"})
    [event] = timeline(client, patient)["items"]
    assert event["record_id"] == c["id"] and event["occurred_at"] == "2025-01-01T00:00:00Z"


def test_timeline_event_shape(client, patient, history):
    events = {e["record_id"]: e for e in timeline(client, patient)["items"]}
    temp = events[history["temp"]["id"]]
    assert temp["title"] == "Body temperature: 39.1 Cel"
    assert temp["encounter_id"] == history["visit"]["id"] and temp["status"] is None
    assert temp["data"] == history["temp"]  # the full underlying record
    visit = events[history["visit"]["id"]]
    assert visit["title"] == "EMERGENCY encounter: Fever" and visit["encounter_id"] == history["visit"]["id"]
    assert visit["status"] == "IN_PROGRESS"
    assert events[history["allergy"]["id"]]["title"] == "Allergy to Penicillin (Severe)"
    assert events[history["condition"]["id"]]["title"] == "Condition (Suspected): Malaria"
    assert events[history["note"]["id"]]["title"] == "Progress note by Dr. B"


def test_same_timestamp_ordering_is_deterministic(client, patient):
    """All five record types at the same instant, created in scrambled order."""
    created = [
        post(client, patient, "allergies", {"substance": "Latex", "recorded_at": T}),
        post(client, patient, "observations", {"code": "heart_rate", "value_numeric": 90, "unit": "/min", "effective_at": T}),
        post(client, patient, "conditions", {"name": "Asthma", "recorded_at": T}),
    ]
    encounter = post(client, patient, "encounters", {"encounter_type": "OPD", "reason": "Check", "start_at": T})
    note = post(client, patient, "clinical-notes", {"encounter_id": encounter["id"], "note_type": "OTHER",
                                                    "author_name": "A", "content": "x", "authored_at": T})
    second_obs = post(client, patient, "observations",
                      {"code": "heart_rate", "value_numeric": 95, "unit": "/min", "effective_at": T})

    expected = [encounter["id"], created[1]["id"], second_obs["id"], created[2]["id"], created[0]["id"], note["id"]]
    for order in ("desc", "asc"):
        body = timeline(client, patient, order=order)
        assert [e["record_id"] for e in body["items"]] == expected, order
        assert kinds(body) == ["encounter", "observation", "observation", "condition", "allergy", "clinical_note"]
    # Stable across repeated reads and across page boundaries.
    pages = [timeline(client, patient, limit=2, offset=o)["items"] for o in (0, 2, 4)]
    assert [e["record_id"] for page in pages for e in page] == expected


def test_filter_by_type(client, patient, history):
    body = timeline(client, patient, types=["encounter", "clinical_note"])
    assert body["total"] == 3 and set(kinds(body)) == {"encounter", "clinical_note"}
    assert kinds(timeline(client, patient, types="allergy")) == ["allergy"]


def test_filter_by_time_range_is_inclusive(client, patient, history):
    body = timeline(client, patient, occurred_from="2026-01-15T22:10:00Z", occurred_to="2026-01-15T22:30:00Z",
                    order="asc")
    assert [e["record_id"] for e in body["items"]] == [history["temp"]["id"], history["note"]["id"]]
    assert timeline(client, patient, occurred_to="2024-01-01T00:00:00+00:00")["total"] == 1


def test_pagination(client, patient, history):
    full = [e["record_id"] for e in timeline(client, patient, limit=100)["items"]]
    paged = []
    for offset in range(0, 6, 4):
        body = timeline(client, patient, limit=4, offset=offset)
        assert body["total"] == 6 and body["limit"] == 4 and body["offset"] == offset
        paged += [e["record_id"] for e in body["items"]]
    assert paged == full
    assert timeline(client, patient, offset=50)["items"] == []


def test_timeline_reflects_status_changes_without_duplicates(client, patient, history):
    ok(client.post(f"/api/encounters/{history['visit']['id']}/finish", json={"end_at": "2026-01-16T08:00:00Z"}))
    body = timeline(client, patient)
    visit_events = [e for e in body["items"] if e["record_id"] == history["visit"]["id"]]
    assert len(visit_events) == 1 and visit_events[0]["status"] == "FINISHED"
    assert body["total"] == 6


def test_timeline_only_contains_this_patient(client, patient, patient_payload, history):
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Zed")), 201)
    post(client, other, "allergies", {"substance": "Peanut"})
    assert timeline(client, patient)["total"] == 6
    assert timeline(client, other)["total"] == 1


def test_empty_timeline_and_errors(client, patient):
    assert timeline(client, patient) == {
        "patient_id": patient["id"], "items": [], "total": 0, "limit": 20, "offset": 0, "order": "desc"}
    assert client.get(f"/api/patients/{uuid.uuid4()}/timeline").status_code == 404
    assert client.get("/api/patients/nope/timeline").status_code == 422
    base = f"/api/patients/{patient['id']}/timeline"
    assert client.get(base, params={"types": "imaging_study"}).status_code == 422
    assert client.get(base, params={"order": "sideways"}).status_code == 422
    assert client.get(base, params={"occurred_from": "2026-01-01T00:00:00"}).status_code == 422
    assert client.get(base, params={"occurred_from": "2026-02-01T00:00:00Z",
                                    "occurred_to": "2026-01-01T00:00:00Z"}).status_code == 422
    assert client.get(base, params={"limit": 101}).status_code == 422


def test_inactive_patient_timeline_still_readable(client, patient, history):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Transferred"}))
    assert timeline(client, patient)["total"] == 6


def test_no_timeline_table_exists(test_engine):
    """The timeline is derived on read; nothing is duplicated into a timeline table."""
    # audit_events (Stage 6) is the security audit trail, not a copy of clinical timeline events.
    tables = set(inspect(test_engine).get_table_names()) - {"audit_events"}
    assert not [t for t in tables if "timeline" in t or "event" in t]
    with test_engine.connect() as connection:
        views = connection.execute(text("SELECT count(*) FROM pg_views WHERE schemaname = 'public'")).scalar_one()
    assert views == 0
