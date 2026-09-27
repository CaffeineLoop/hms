"""Clinical read authorization (pre UI-2): every patient clinical-record read needs the record's view permission
AND patient.view, both at ALL scope. OWN grants no record-level access to clinical records.

Covers every patient-scoped list and ID-only read of encounters, observations, conditions, allergies, clinical
notes, the timeline, lab orders/samples/results, reports and prescriptions. The check runs before any lookup, so
denied callers get the same 403 for real and unknown ids and never see clinical content.
"""

import json
import uuid

import pytest
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

SCOPE_DENIED = "You are not permitted to view patients' clinical records."
MARKER = "Marker-b7e1"  # appears in every clinical record of patient B
T0 = "2026-02-01T08:00:00Z"

# (endpoint id, path template, permission). Templates use the ids of patient B's chart.
ENDPOINTS = [
    ("encounters", "/api/patients/{patient}/encounters", "encounter.view"),
    ("encounter", "/api/encounters/{encounter}", "encounter.view"),
    ("patient-encounter", "/api/patients/{patient}/encounters/{encounter}", "encounter.view"),
    ("observations", "/api/patients/{patient}/observations", "observation.view"),
    ("observation", "/api/observations/{observation}", "observation.view"),
    ("conditions", "/api/patients/{patient}/conditions", "condition.view"),
    ("condition", "/api/conditions/{condition}", "condition.view"),
    ("allergies", "/api/patients/{patient}/allergies", "allergy.view"),
    ("allergy", "/api/allergies/{allergy}", "allergy.view"),
    ("notes", "/api/patients/{patient}/clinical-notes", "clinical_note.view"),
    ("note", "/api/clinical-notes/{note}", "clinical_note.view"),
    ("timeline", "/api/patients/{patient}/timeline", "timeline.view"),
    ("lab-orders", "/api/patients/{patient}/lab-orders", "lab.view"),
    ("lab-order", "/api/lab-orders/{lab_order}", "lab.view"),
    ("lab-sample", "/api/lab-samples/{lab_sample}", "lab.view"),
    ("lab-result", "/api/lab-results/{lab_result}", "lab.view"),
    ("reports", "/api/patients/{patient}/reports", "report.view"),
    ("report", "/api/reports/{report}", "report.view"),
    ("prescriptions", "/api/patients/{patient}/prescriptions", "prescription.view"),
    ("prescription", "/api/prescriptions/{prescription}", "prescription.view"),
]
IDS = [e[0] for e in ENDPOINTS]
CLINICAL = sorted({e[2] for e in ENDPOINTS})


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def get(auth_client, user, path):
    return auth_client.get(path, headers=user["headers"])


def make_role(client, name: str, grants: dict[str, str]) -> None:
    ok(client.post("/api/roles", json={"name": name, "permissions": [
        {"code": code, "scope": scope} for code, scope in grants.items()]}), 201)


@pytest.fixture
def since(test_engine):
    with test_engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar_one()


@pytest.fixture
def events(test_engine, since):
    def fetch(**filters) -> list[dict]:
        clauses = " ".join(f"AND {k} = :{k}" for k in filters)
        with test_engine.connect() as c:
            rows = c.execute(text(f"SELECT * FROM audit_events WHERE occurred_at >= :since {clauses} "
                                  "ORDER BY occurred_at, id"), {"since": since, **filters}).mappings().all()
        return [dict(r) for r in rows]

    return fetch


def build_chart(client, patient: dict, marker: str) -> dict:
    pid = patient["id"]
    enc = ok(client.post(f"/api/patients/{pid}/encounters",
                         json={"encounter_type": "OPD", "reason": f"Reason {marker}", "start_at": T0}), 201)
    obs = ok(client.post(f"/api/patients/{pid}/observations", json={
        "code": "heart_rate", "value_numeric": 88, "unit": "/min", "effective_at": "2026-02-01T08:10:00Z",
        "encounter_id": enc["id"], "notes": f"Obs {marker}"}), 201)
    cond = ok(client.post(f"/api/patients/{pid}/conditions", json={"name": "Hypertension", "status": "ACTIVE",
                                                                 "notes": f"Cond {marker}"}), 201)
    allergy = ok(client.post(f"/api/patients/{pid}/allergies", json={"substance": "Penicillin", "severity": "SEVERE",
                                                                    "reaction": f"Rash {marker}"}), 201)
    note = ok(client.post(f"/api/patients/{pid}/clinical-notes", json={
        "encounter_id": enc["id"], "note_type": "PROGRESS", "author_name": "Dr. A", "content": f"Note {marker}"}), 201)
    order = ok(client.post(f"/api/patients/{pid}/lab-orders", json={
        "encounter_id": enc["id"], "test_code": "fbc", "test_name": "Full blood count",
        "clinical_indication": f"Pallor {marker}", "ordered_by": "Dr. A", "ordered_at": "2026-02-01T08:20:00Z"}), 201)
    sample = ok(client.post(f"/api/lab-orders/{order['id']}/samples", json={
        "specimen_type": "BLOOD", "collected_by": "Nurse", "collected_at": "2026-02-01T08:30:00Z"}), 201)
    ok(client.post(f"/api/lab-orders/{order['id']}/start-processing"))
    resulted = ok(client.post(f"/api/lab-orders/{order['id']}/results", json={"entered_by": "Tech", "results": [
        {"analyte_code": "hemoglobin", "analyte_name": "Hemoglobin", "value_numeric": 9.2, "unit": "g/dL",
         "resulted_at": "2026-02-01T09:30:00Z", "notes": f"Result {marker}"}]}))
    report = ok(client.post(f"/api/patients/{pid}/reports", json={
        "report_type": "IMAGING", "title": f"Chest X-ray {marker}", "author_name": "Dr. Radiologist",
        "effective_at": "2026-02-01T11:00:00Z"}), 201)
    rx = ok(client.post(f"/api/patients/{pid}/prescriptions", json={
        "encounter_id": enc["id"], "prescriber_name": "Dr. N", "notes": f"Rx {marker}", "items": [
            {"medicine_name": "Paracetamol", "dose_value": 1, "dose_unit": "g", "route": "ORAL", "frequency": "QID"}]}), 201)
    return {"patient": pid, "encounter": enc["id"], "observation": obs["id"], "condition": cond["id"],
            "allergy": allergy["id"], "note": note["id"], "lab_order": order["id"], "lab_sample": sample["id"],
            "lab_result": resulted["results"][0]["id"], "report": report["id"], "prescription": rx["id"]}


@pytest.fixture
def charts(client, patient_payload) -> dict:
    a = ok(client.post("/api/patients", json=patient_payload(first_name="Alpha", date_of_birth="1970-01-01")), 201)
    b = ok(client.post("/api/patients", json=patient_payload(first_name="Bravo", date_of_birth="1971-01-01")), 201)
    return {"a": build_chart(client, a, "a-visible"), "b": build_chart(client, b, MARKER), "b_patient": b}


def assert_no_leak(response, charts) -> None:
    b = charts["b_patient"]
    for value in (MARKER, b["id"], b["first_name"], b["patient_number"]):
        assert value not in response.text, f"leaked {value!r}"


def unknown_path(template: str) -> str:
    return template.format(**{k: uuid.uuid4() for k in (
        "patient", "encounter", "observation", "condition", "allergy", "note", "lab_order", "lab_sample",
        "lab_result", "report", "prescription")})


# --- authorized ALL-scope access ----------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["DOCTOR", "NURSE", "SUPER_ADMIN"])
def test_all_scope_roles_keep_access_to_every_clinical_read(auth_client, make_user, charts, role):
    user = make_user(role)
    for name, template, _ in ENDPOINTS:
        body = ok(get(auth_client, user, template.format(**charts["b"])))
        assert body, name
    timeline = ok(get(auth_client, user, f"/api/patients/{charts['b']['patient']}/timeline?limit=100"))
    assert {"encounter", "observation", "condition", "allergy", "clinical_note"} <= {
        e["event_type"] for e in timeline["items"]}


def test_all_scope_unknown_ids_are_404(auth_client, make_user):
    doctor = make_user("DOCTOR")
    for name, template, _ in ENDPOINTS:  # unknown record ids, and unknown patients for patient-scoped reads
        assert get(auth_client, doctor, unknown_path(template)).status_code == 404, name


# --- OWN scope and missing permissions are denied before anything is loaded --------------------------------


DENIED_CALLERS = [
    ("clinical-own", {**{p: "OWN" for p in CLINICAL}, "patient.view": "ALL"}, lambda perm: SCOPE_DENIED),
    ("patient-own", {**{p: "ALL" for p in CLINICAL}, "patient.view": "OWN"}, lambda perm: SCOPE_DENIED),
    ("no-patient-view", {p: "ALL" for p in CLINICAL}, lambda perm: "Missing permission: patient.view."),
    ("no-clinical-permission", {"patient.view": "ALL"}, lambda perm: f"Missing permission: {perm}."),
]


@pytest.mark.parametrize(("name", "grants", "detail"), DENIED_CALLERS, ids=[d[0] for d in DENIED_CALLERS])
def test_denied_callers_get_403_on_real_and_unknown_ids_without_leaks(auth_client, client, make_user, charts,
                                                                       name, grants, detail):
    role = f"SCOPE_{name.upper().replace('-', '_')}"
    make_role(client, role, grants)
    user = make_user(role)
    for endpoint, template, perm in ENDPOINTS:
        for path in (template.format(**charts["b"]), unknown_path(template)):
            response = get(auth_client, user, path)
            assert response.status_code == 403, (endpoint, path, response.status_code)
            assert response.json()["detail"] == detail(perm), endpoint
            assert_no_leak(response, charts)


def test_own_scope_is_checked_per_permission(auth_client, client, make_user, charts):
    """OWN on one clinical permission blocks only that record type; the others stay readable."""
    grants = {**{p: "ALL" for p in CLINICAL}, "patient.view": "ALL", "observation.view": "OWN"}
    make_role(client, "SCOPE_OBS_OWN", grants)
    user = make_user("SCOPE_OBS_OWN")
    for endpoint, template, perm in ENDPOINTS:
        response = get(auth_client, user, template.format(**charts["b"]))
        expected = 403 if perm == "observation.view" else 200
        assert response.status_code == expected, endpoint
    # The timeline omits event types whose permission is only OWN-scoped.
    timeline = ok(get(auth_client, user, f"/api/patients/{charts['b']['patient']}/timeline?limit=100"))
    types = {e["event_type"] for e in timeline["items"]}
    assert "observation" not in types and {"encounter", "condition", "allergy", "clinical_note"} <= types


# --- no cross-patient leakage --------------------------------------------------------------------------------


def test_patient_scoped_reads_never_include_another_patients_records(auth_client, make_user, charts):
    doctor = make_user("DOCTOR")
    for endpoint, template, _ in ENDPOINTS:
        if "{patient}" not in template or "{encounter}" in template:
            continue
        response = ok(get(auth_client, doctor, template.format(**charts["a"])))
        assert MARKER not in json.dumps(response), endpoint
        assert charts["b"]["patient"] not in json.dumps(response), endpoint
    wrong = get(auth_client, doctor, f"/api/patients/{charts['a']['patient']}/encounters/{charts['b']['encounter']}")
    assert wrong.status_code == 404
    assert_no_leak(wrong, charts)


# --- audit ---------------------------------------------------------------------------------------------------


def test_successful_and_denied_clinical_reads_are_audited_without_content(auth_client, client, make_user, charts,
                                                                          events):
    doctor = make_user("DOCTOR")
    make_role(client, "SCOPE_AUDIT_OWN", {**{p: "OWN" for p in CLINICAL}, "patient.view": "ALL"})
    limited = make_user("SCOPE_AUDIT_OWN")
    b = charts["b"]
    ok(get(auth_client, doctor, f"/api/patients/{b['patient']}/clinical-notes"))
    ok(get(auth_client, doctor, f"/api/observations/{b['observation']}"))
    assert get(auth_client, limited, f"/api/patients/{b['patient']}/clinical-notes").status_code == 403
    assert get(auth_client, limited, f"/api/prescriptions/{b['prescription']}").status_code == 403

    [read_list] = [e for e in events(action="GET /api/patients/{patient_id}/clinical-notes")
                   if str(e["actor_user_id"]) == doctor["user"]["id"]]
    assert read_list["outcome"] == "SUCCESS" and str(read_list["patient_id"]) == b["patient"]
    [read_one] = events(action="GET /api/observations/{observation_id}")
    assert read_one["outcome"] == "SUCCESS" and read_one["resource_id"] == b["observation"]
    denied = [e for e in events() if e["outcome"] == "DENIED" and str(e["actor_user_id"]) == limited["user"]["id"]]
    assert {e["action"] for e in denied} == {"GET /api/patients/{patient_id}/clinical-notes",
                                             "GET /api/prescriptions/{prescription_id}"}
    assert all(e["status_code"] == 403 for e in denied)
    assert MARKER not in json.dumps(events(), default=str)
