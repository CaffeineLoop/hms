"""Laboratory workflow end-to-end against the isolated test database (hms_test)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

T0 = "2026-03-02T08:00:00Z"


def at(minutes: int) -> str:
    return (datetime(2026, 3, 2, 8, tzinfo=UTC) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1975-07-07")), 201)


@pytest.fixture
def encounter(client, patient) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/encounters",
                          json={"encounter_type": "OPD", "reason": "Fatigue", "start_at": T0}), 201)


@pytest.fixture
def order(client, patient, encounter) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/lab-orders", json={
        "encounter_id": encounter["id"], "test_code": "full_blood_count", "test_name": "Full blood count",
        "code_system": "http://loinc.org", "system_code": "58410-2", "priority": "URGENT",
        "clinical_indication": "Pallor", "ordered_by": "Dr. Mwangi", "ordered_at": at(10)}), 201)


def collect(client, order, minutes=20) -> dict:
    return ok(client.post(f"/api/lab-orders/{order['id']}/samples", json={
        "specimen_type": "BLOOD", "collected_by": "Nurse Atieno", "collected_at": at(minutes)}), 201)


RESULTS = {
    "entered_by": "Tech Kiprop",
    "results": [
        {"analyte_code": "hemoglobin", "analyte_name": "Hemoglobin", "code_system": "http://loinc.org",
         "system_code": "718-7", "value_numeric": 9.2, "unit": "g/dL", "reference_low": 12, "reference_high": 16,
         "resulted_at": at(90)},
        {"analyte_code": "wbc", "analyte_name": "White blood cells", "value_numeric": 7.1, "unit": "10*3/uL",
         "reference_low": 4, "reference_high": 11, "resulted_at": at(90)},
    ],
}


def to_status(client, order, target: str) -> dict:
    """Drive an order along the happy path up to `target`."""
    steps = {
        "SAMPLE_COLLECTED": lambda: collect(client, order),
        "PROCESSING": lambda: ok(client.post(f"/api/lab-orders/{order['id']}/start-processing")),
        "RESULT_ENTERED": lambda: ok(client.post(f"/api/lab-orders/{order['id']}/results", json=RESULTS)),
        "VERIFIED": lambda: ok(client.post(f"/api/lab-orders/{order['id']}/verify", json={"verified_by": "Dr. Lab"})),
        "RELEASED": lambda: ok(client.post(f"/api/lab-orders/{order['id']}/release")),
    }
    for status, step in steps.items():
        step()
        if status == target:
            break
    return ok(client.get(f"/api/lab-orders/{order['id']}"))


# --- lifecycle --------------------------------------------------------------------------


def test_create_lab_order(client, order, patient, encounter):
    assert re.fullmatch(r"LAB-\d{6}", order["order_number"])
    assert order["status"] == "ORDERED" and order["priority"] == "URGENT"
    assert order["patient_id"] == patient["id"] and order["encounter_id"] == encounter["id"]
    assert order["ordered_at"] == at(10) and order["samples"] == [] and order["results"] == []


def test_full_lifecycle(client, order):
    sample = collect(client, order)
    assert re.fullmatch(r"SMP-\d{6}", sample["accession_number"]) and sample["lab_order_id"] == order["id"]
    assert ok(client.get(f"/api/lab-orders/{order['id']}"))["status"] == "SAMPLE_COLLECTED"
    assert ok(client.get(f"/api/lab-samples/{sample['id']}")) == sample

    processing = ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
    assert processing["status"] == "PROCESSING" and processing["processing_started_at"]

    entered = ok(client.post(f"/api/lab-orders/{order['id']}/results", json=RESULTS))
    assert entered["status"] == "RESULT_ENTERED" and entered["results_entered_at"]
    by_code = {r["analyte_code"]: r for r in entered["results"]}
    assert by_code["hemoglobin"]["interpretation"] == "LOW"
    assert by_code["wbc"]["interpretation"] == "NORMAL"
    assert by_code["hemoglobin"]["entered_by"] == "Tech Kiprop"

    verified = ok(client.post(f"/api/lab-orders/{order['id']}/verify", json={"verified_by": "Dr. Lab"}))
    assert verified["status"] == "VERIFIED" and verified["verified_by"] == "Dr. Lab" and verified["verified_at"]

    released = ok(client.post(f"/api/lab-orders/{order['id']}/release"))
    assert released["status"] == "RELEASED" and released["released_at"] >= released["verified_at"]
    assert [s["id"] for s in released["samples"]] == [sample["id"]] and len(released["results"]) == 2


def test_additional_sample_and_results_in_batches(client, order):
    collect(client, order, minutes=20)
    collect(client, order, minutes=25)  # re-collection while SAMPLE_COLLECTED is allowed
    ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
    first = {"entered_by": "Tech", "results": [RESULTS["results"][0]]}
    second = {"entered_by": "Tech", "results": [RESULTS["results"][1]]}
    ok(client.post(f"/api/lab-orders/{order['id']}/results", json=first))
    body = ok(client.post(f"/api/lab-orders/{order['id']}/results", json=second))
    assert len(body["samples"]) == 2 and len(body["results"]) == 2 and body["status"] == "RESULT_ENTERED"


@pytest.mark.parametrize(
    ("reach", "action", "body"),
    [
        ("ORDERED", "start-processing", None),
        ("ORDERED", "results", RESULTS),
        ("ORDERED", "verify", {"verified_by": "x"}),
        ("ORDERED", "release", None),
        ("SAMPLE_COLLECTED", "results", RESULTS),
        ("SAMPLE_COLLECTED", "verify", {"verified_by": "x"}),
        ("PROCESSING", "verify", {"verified_by": "x"}),
        ("PROCESSING", "start-processing", None),
        ("RESULT_ENTERED", "release", None),
        ("VERIFIED", "results", {"entered_by": "x", "results": [{**RESULTS["results"][0], "analyte_code": "mcv"}]}),
        ("VERIFIED", "cancel", {"reason": "x"}),
        ("VERIFIED", "verify", {"verified_by": "x"}),
        ("RELEASED", "cancel", {"reason": "x"}),
        ("RELEASED", "release", None),
    ],
)
def test_invalid_lab_transitions_are_409(client, order, reach, action, body):
    if reach != "ORDERED":
        to_status(client, order, reach)
    before = ok(client.get(f"/api/lab-orders/{order['id']}"))
    response = client.post(f"/api/lab-orders/{order['id']}/{action}", json=body)
    assert response.status_code == 409, response.text
    assert ok(client.get(f"/api/lab-orders/{order['id']}")) == before


@pytest.mark.parametrize("reach", ["RESULT_ENTERED", "VERIFIED", "RELEASED"])
def test_no_samples_after_processing_finished(client, order, reach):
    to_status(client, order, reach)
    response = client.post(f"/api/lab-orders/{order['id']}/samples",
                           json={"specimen_type": "BLOOD", "collected_by": "N"})
    assert response.status_code == 409


@pytest.mark.parametrize("reach", ["ORDERED", "SAMPLE_COLLECTED", "PROCESSING", "RESULT_ENTERED"])
def test_cancel_allowed_before_verification(client, order, reach):
    if reach != "ORDERED":
        to_status(client, order, reach)
    cancelled = ok(client.post(f"/api/lab-orders/{order['id']}/cancel", json={"reason": "Sample haemolysed"}))
    assert cancelled["status"] == "CANCELLED" and cancelled["cancellation_reason"] == "Sample haemolysed"
    assert client.post(f"/api/lab-orders/{order['id']}/samples",
                       json={"specimen_type": "BLOOD", "collected_by": "N"}).status_code == 409


def test_cancel_requires_reason(client, order):
    assert client.post(f"/api/lab-orders/{order['id']}/cancel", json={}).status_code == 422


# --- results validation / corrections -----------------------------------------------------


def test_duplicate_analyte_is_409(client, order):
    to_status(client, order, "RESULT_ENTERED")
    response = client.post(f"/api/lab-orders/{order['id']}/results",
                           json={"entered_by": "x", "results": [RESULTS["results"][0]]})
    assert response.status_code == 409 and "hemoglobin" in response.json()["detail"]


@pytest.mark.parametrize(
    "bad",
    [
        {"value_numeric": None},
        {"value_text": "low"},
        {"reference_low": 20},
        {"unit": None, "value_numeric": None, "value_text": "x"},
        {"resulted_at": "2026-03-02T08:00:00"},
        {"interpretation": "BAD"},
    ],
)
def test_invalid_results_are_422(client, order, bad):
    to_status(client, order, "PROCESSING")
    body = {"entered_by": "Tech", "results": [{**RESULTS["results"][0], **bad}]}
    assert client.post(f"/api/lab-orders/{order['id']}/results", json=body).status_code == 422
    assert ok(client.get(f"/api/lab-orders/{order['id']}"))["results"] == []


def test_result_before_sample_collection_is_422(client, order):
    to_status(client, order, "PROCESSING")
    body = {"entered_by": "Tech", "results": [{**RESULTS["results"][0], "resulted_at": at(15)}]}
    response = client.post(f"/api/lab-orders/{order['id']}/results", json=body)
    assert response.status_code == 422 and "sample collection" in response.json()["detail"][0]["msg"]


def test_submission_is_all_or_nothing(client, order):
    to_status(client, order, "PROCESSING")
    body = {"entered_by": "Tech", "results": [RESULTS["results"][1], {**RESULTS["results"][0], "resulted_at": at(15)}]}
    assert client.post(f"/api/lab-orders/{order['id']}/results", json=body).status_code == 422
    after = ok(client.get(f"/api/lab-orders/{order['id']}"))
    assert after["results"] == [] and after["status"] == "PROCESSING"


def test_correct_result_before_verification(client, order):
    entered = to_status(client, order, "RESULT_ENTERED")
    hb = next(r for r in entered["results"] if r["analyte_code"] == "hemoglobin")
    corrected = ok(client.patch(f"/api/lab-results/{hb['id']}", json={"value_numeric": 13.1, "entered_by": "Tech 2"}))
    assert corrected["value_numeric"] == 13.1 and corrected["interpretation"] == "NORMAL"  # re-derived
    assert corrected["entered_by"] == "Tech 2"
    flagged = ok(client.patch(f"/api/lab-results/{hb['id']}", json={"interpretation": "ABNORMAL", "entered_by": "T"}))
    assert flagged["interpretation"] == "ABNORMAL"
    assert ok(client.get(f"/api/lab-results/{hb['id']}")) == flagged


def test_invalid_correction_is_422(client, order):
    entered = to_status(client, order, "RESULT_ENTERED")
    hb = entered["results"][0]
    assert client.patch(f"/api/lab-results/{hb['id']}",
                        json={"reference_low": 99, "entered_by": "T"}).status_code == 422
    assert client.patch(f"/api/lab-results/{hb['id']}",
                        json={"value_text": "high", "entered_by": "T"}).status_code == 422


@pytest.mark.parametrize("reach", ["VERIFIED", "RELEASED"])
def test_results_locked_after_verification(client, order, reach):
    body = to_status(client, order, reach)
    response = client.patch(f"/api/lab-results/{body['results'][0]['id']}", json={"value_numeric": 1, "entered_by": "T"})
    assert response.status_code == 409 and "locked" in response.json()["detail"]


def test_verify_requires_results(client, order, test_engine):
    """Normal use always creates results before RESULT_ENTERED; force the edge case in the DB."""
    from sqlalchemy import text

    with test_engine.begin() as connection:
        connection.execute(text("UPDATE lab_orders SET status = 'RESULT_ENTERED' WHERE id = :id"), {"id": order["id"]})
    response = client.post(f"/api/lab-orders/{order['id']}/verify", json={"verified_by": "x"})
    assert response.status_code == 409 and "no results" in response.json()["detail"]


# --- relationships / validation / missing --------------------------------------------------


def test_order_requires_patients_own_started_encounter(client, patient, encounter, patient_payload):
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Other")), 201)
    body = {"encounter_id": encounter["id"], "test_code": "malaria_rdt", "test_name": "Malaria RDT", "ordered_by": "A"}
    assert client.post(f"/api/patients/{other['id']}/lab-orders", json=body).status_code == 422
    planned = ok(client.post(f"/api/patients/{patient['id']}/encounters", json={
        "encounter_type": "OPD", "reason": "Booked", "status": "PLANNED", "start_at": T0}), 201)
    assert client.post(f"/api/patients/{patient['id']}/lab-orders",
                       json={**body, "encounter_id": planned["id"]}).status_code == 409
    assert client.post(f"/api/patients/{patient['id']}/lab-orders",
                       json={**body, "encounter_id": str(uuid.uuid4())}).status_code == 422
    early = {**body, "ordered_at": at(-60)}
    assert client.post(f"/api/patients/{patient['id']}/lab-orders", json=early).status_code == 422


def test_sample_before_order_is_422(client, order):
    response = client.post(f"/api/lab-orders/{order['id']}/samples",
                           json={"specimen_type": "BLOOD", "collected_by": "N", "collected_at": at(0)})
    assert response.status_code == 422


def test_no_orders_for_inactive_patient_but_workflow_continues(client, patient, order):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Transferred"}))
    body = {"encounter_id": order["encounter_id"], "test_code": "x", "test_name": "X", "ordered_by": "A"}
    assert client.post(f"/api/patients/{patient['id']}/lab-orders", json=body).status_code == 409
    assert to_status(client, order, "RELEASED")["status"] == "RELEASED"


def test_list_lab_orders(client, patient, encounter, order):
    second = ok(client.post(f"/api/patients/{patient['id']}/lab-orders", json={
        "encounter_id": encounter["id"], "test_code": "malaria_rdt", "test_name": "Malaria RDT",
        "ordered_by": "A", "ordered_at": at(30)}), 201)
    ok(client.post(f"/api/lab-orders/{order['id']}/cancel", json={"reason": "Duplicate"}))
    body = ok(client.get(f"/api/patients/{patient['id']}/lab-orders"))
    assert [o["id"] for o in body["items"]] == [second["id"], order["id"]] and body["total"] == 2
    assert ok(client.get(f"/api/patients/{patient['id']}/lab-orders", params={"status": "CANCELLED"}))["total"] == 1
    assert ok(client.get(f"/api/patients/{patient['id']}/lab-orders", params={"test_code": "MALARIA_RDT"}))["total"] == 1
    assert ok(client.get(f"/api/patients/{patient['id']}/lab-orders", params={"limit": 1}))["items"][0]["id"] == second["id"]


@pytest.mark.parametrize("path", ["lab-orders", "lab-samples", "lab-results"])
def test_missing_and_invalid_ids(client, path):
    assert client.get(f"/api/{path}/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/{path}/not-a-uuid").status_code == 422
    assert client.delete(f"/api/{path}/{uuid.uuid4()}").status_code == 405


@pytest.mark.parametrize("action", ["samples", "start-processing", "results", "verify", "release", "cancel"])
def test_actions_on_missing_order_are_404(client, action):
    body = {
        "samples": {"specimen_type": "BLOOD", "collected_by": "N"}, "results": RESULTS,
        "verify": {"verified_by": "x"}, "cancel": {"reason": "x"},
    }.get(action)
    assert client.post(f"/api/lab-orders/{uuid.uuid4()}/{action}", json=body).status_code == 404


def test_missing_patient(client):
    assert client.get(f"/api/patients/{uuid.uuid4()}/lab-orders").status_code == 404
    body = {"encounter_id": str(uuid.uuid4()), "test_code": "x", "test_name": "X", "ordered_by": "A"}
    assert client.post(f"/api/patients/{uuid.uuid4()}/lab-orders", json=body).status_code == 404
    assert client.patch(f"/api/lab-results/{uuid.uuid4()}", json={"value_numeric": 1, "entered_by": "t"}).status_code == 404
