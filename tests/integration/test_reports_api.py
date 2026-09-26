"""Reports end-to-end against the isolated test database (hms_test)."""

import uuid

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

T0 = "2026-04-01T10:00:00Z"


def ok(response, status: int = 200) -> dict:
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture
def patient(client, patient_payload) -> dict:
    return ok(client.post("/api/patients", json=patient_payload(date_of_birth="1960-02-02")), 201)


@pytest.fixture
def encounter(client, patient) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/encounters",
                          json={"encounter_type": "INPATIENT", "reason": "Pneumonia", "start_at": T0}), 201)


def create(client, patient, **overrides) -> dict:
    body = {"report_type": "IMAGING", "title": "Chest X-ray PA", "author_name": "Dr. Radiologist",
            "code_system": "http://loinc.org", "code": "36643-5", "effective_at": "2026-04-01T11:00:00Z",
            "requested_by": "Dr. Ward", "requested_at": "2026-04-01T10:30:00Z", **overrides}
    return ok(client.post(f"/api/patients/{patient['id']}/reports", json=body), 201)


def test_create_and_retrieve_report(client, patient, encounter):
    response = client.post(f"/api/patients/{patient['id']}/reports", json={
        "report_type": "IMAGING", "title": "Chest X-ray PA", "author_name": "Dr. R", "encounter_id": encounter["id"],
        "effective_at": "2026-04-01T11:00:00Z", "content": "Right lower lobe consolidation."})
    report = ok(response, 201)
    assert response.headers["Location"] == f"/api/reports/{report['id']}"
    assert report["status"] == "DRAFT" and report["encounter_id"] == encounter["id"]
    assert report["verified_at"] is None and report["released_at"] is None
    assert ok(client.get(f"/api/reports/{report['id']}")) == report


def test_report_lifecycle(client, patient, encounter):
    report = create(client, patient, encounter_id=encounter["id"])
    assert report["content"] is None and report["requested_by"] == "Dr. Ward"
    edited = ok(client.patch(f"/api/reports/{report['id']}", json={
        "content": "Consolidation right lower lobe.", "conclusion": "Findings consistent with pneumonia."}))
    assert edited["content"].startswith("Consolidation")
    verified = ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "Dr. Senior"}))
    assert verified["status"] == "VERIFIED" and verified["verified_by"] == "Dr. Senior"
    released = ok(client.post(f"/api/reports/{report['id']}/release"))
    assert released["status"] == "RELEASED" and released["released_at"] >= released["verified_at"]


@pytest.mark.parametrize("report_type", ["LABORATORY", "IMAGING", "CONSULTATION", "DISCHARGE", "PROCEDURE", "OTHER"])
def test_all_report_types(client, patient, report_type):
    assert create(client, patient, report_type=report_type)["report_type"] == report_type


def test_verify_requires_content(client, patient):
    report = create(client, patient)
    response = client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "Dr. S"})
    assert response.status_code == 422 and response.json()["detail"][0]["loc"] == ["body", "content"]


@pytest.mark.parametrize(
    ("reach", "action", "body"),
    [
        ("DRAFT", "release", None),
        ("VERIFIED", "verify", {"verified_by": "x"}),
        ("RELEASED", "cancel", {"reason": "x"}),
        ("RELEASED", "release", None),
        ("CANCELLED", "verify", {"verified_by": "x"}),
        ("CANCELLED", "release", None),
    ],
)
def test_invalid_report_transitions_are_409(client, patient, reach, action, body):
    report = create(client, patient, content="Normal study.")
    steps = {"VERIFIED": [("verify", {"verified_by": "v"})],
             "RELEASED": [("verify", {"verified_by": "v"}), ("release", None)],
             "CANCELLED": [("cancel", {"reason": "Wrong patient"})]}.get(reach, [])
    for step, step_body in steps:
        ok(client.post(f"/api/reports/{report['id']}/{step}", json=step_body))
    assert client.post(f"/api/reports/{report['id']}/{action}", json=body).status_code == 409


def test_only_drafts_are_editable(client, patient):
    report = create(client, patient, content="Normal study.")
    ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "v"}))
    assert client.patch(f"/api/reports/{report['id']}", json={"content": "changed"}).status_code == 409


def test_cancel_verified_report(client, patient):
    report = create(client, patient, content="Normal study.")
    ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "v"}))
    cancelled = ok(client.post(f"/api/reports/{report['id']}/cancel", json={"reason": "Entered in error"}))
    assert cancelled["status"] == "CANCELLED" and cancelled["verified_by"] == "v"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"report_type": "IMAGING", "title": "x"},
        {"report_type": "SCAN", "title": "x", "author_name": "a"},
        {"report_type": "IMAGING", "title": "x", "author_name": "a", "effective_at": "2026-04-01T11:00:00"},
        {"report_type": "IMAGING", "title": "x", "author_name": "a", "lab_order_id": str(uuid.uuid4())},
    ],
)
def test_invalid_report_input_is_422(client, patient, body):
    assert client.post(f"/api/patients/{patient['id']}/reports", json=body).status_code == 422


def test_report_timestamps_checked_against_patient_and_encounter(client, patient, encounter):
    body = {"report_type": "OTHER", "title": "x", "author_name": "a"}
    assert client.post(f"/api/patients/{patient['id']}/reports",
                       json={**body, "effective_at": "1950-01-01T00:00:00Z"}).status_code == 422  # before birth
    assert client.post(f"/api/patients/{patient['id']}/reports", json={
        **body, "encounter_id": encounter["id"], "effective_at": "2026-04-01T09:00:00Z"}).status_code == 422


def test_report_encounter_must_belong_to_patient(client, patient, encounter, patient_payload):
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Other")), 201)
    body = {"report_type": "OTHER", "title": "x", "author_name": "a", "encounter_id": encounter["id"]}
    assert client.post(f"/api/patients/{other['id']}/reports", json=body).status_code == 422


# --- laboratory report linked to a lab order -------------------------------------------------


@pytest.fixture
def lab_order(client, patient, encounter) -> dict:
    return ok(client.post(f"/api/patients/{patient['id']}/lab-orders", json={
        "encounter_id": encounter["id"], "test_code": "blood_culture", "test_name": "Blood culture",
        "ordered_by": "Dr. W", "ordered_at": "2026-04-01T10:05:00Z"}), 201)


def release_order(client, order):
    ok(client.post(f"/api/lab-orders/{order['id']}/samples", json={
        "specimen_type": "BLOOD", "collected_by": "N", "collected_at": "2026-04-01T10:10:00Z"}), 201)
    ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
    ok(client.post(f"/api/lab-orders/{order['id']}/results", json={"entered_by": "T", "results": [
        {"analyte_code": "culture", "analyte_name": "Culture", "value_text": "No growth at 48 h"}]}))
    ok(client.post(f"/api/lab-orders/{order['id']}/verify", json={"verified_by": "Dr. Micro"}))
    ok(client.post(f"/api/lab-orders/{order['id']}/release"))


def test_laboratory_report_waits_for_released_results(client, patient, lab_order):
    report = create(client, patient, report_type="LABORATORY", title="Blood culture report",
                    lab_order_id=lab_order["id"], content="No growth.")
    assert report["lab_order_id"] == lab_order["id"]
    ok(client.post(f"/api/reports/{report['id']}/verify", json={"verified_by": "Dr. Micro"}))
    response = client.post(f"/api/reports/{report['id']}/release")
    assert response.status_code == 409 and "must be RELEASED" in response.json()["detail"]
    release_order(client, lab_order)
    assert ok(client.post(f"/api/reports/{report['id']}/release"))["status"] == "RELEASED"


def test_laboratory_report_order_rules(client, patient, lab_order, patient_payload):
    other = ok(client.post("/api/patients", json=patient_payload(first_name="Other")), 201)
    body = {"report_type": "LABORATORY", "title": "x", "author_name": "a", "lab_order_id": lab_order["id"]}
    assert client.post(f"/api/patients/{other['id']}/reports", json=body).status_code == 422
    assert client.post(f"/api/patients/{patient['id']}/reports",
                       json={**body, "lab_order_id": str(uuid.uuid4())}).status_code == 422
    ok(client.post(f"/api/lab-orders/{lab_order['id']}/cancel", json={"reason": "Lost sample"}))
    assert client.post(f"/api/patients/{patient['id']}/reports", json=body).status_code == 409


# --- listing / missing ---------------------------------------------------------------------


def test_list_reports(client, patient, encounter):
    a = create(client, patient, effective_at="2026-04-01T11:00:00Z")
    b = create(client, patient, report_type="DISCHARGE", title="Discharge summary", effective_at="2026-04-03T09:00:00Z",
               encounter_id=encounter["id"])
    body = ok(client.get(f"/api/patients/{patient['id']}/reports"))
    assert [r["id"] for r in body["items"]] == [b["id"], a["id"]]
    assert ok(client.get(f"/api/patients/{patient['id']}/reports", params={"report_type": "DISCHARGE"}))["total"] == 1
    assert ok(client.get(f"/api/patients/{patient['id']}/reports", params={"status": "RELEASED"}))["total"] == 0
    assert ok(client.get(f"/api/patients/{patient['id']}/reports", params={"encounter_id": encounter["id"]}))["total"] == 1


def test_missing_resources(client, patient):
    assert client.get(f"/api/reports/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/reports/abc").status_code == 422
    assert client.patch(f"/api/reports/{uuid.uuid4()}", json={"content": "x"}).status_code == 404
    assert client.post(f"/api/reports/{uuid.uuid4()}/release").status_code == 404
    assert client.get(f"/api/patients/{uuid.uuid4()}/reports").status_code == 404
    assert client.delete(f"/api/reports/{uuid.uuid4()}").status_code == 405


def test_no_reports_for_inactive_patient(client, patient):
    ok(client.post(f"/api/patients/{patient['id']}/deactivate", json={"reason": "Deceased"}))
    body = {"report_type": "OTHER", "title": "x", "author_name": "a"}
    assert client.post(f"/api/patients/{patient['id']}/reports", json=body).status_code == 409
