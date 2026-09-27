"""Stage 5 authorization, enforced by the backend: real users, real roles, direct API calls."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]

ROLES = ("SUPER_ADMIN", "DOCTOR", "NURSE", "RECEPTIONIST", "LAB_TECHNICIAN", "PHARMACIST")


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@pytest.fixture
def users(make_user, make_department) -> dict:
    dept = make_department(name="Medicine")
    return {role: make_user(role, department=dept) for role in ROLES}


@pytest.fixture
def chart(client, patient_payload) -> dict:
    """A patient with an in-progress encounter, created by the full-access test principal."""
    patient = ok(client.post("/api/patients", json=patient_payload()), 201)
    encounter = ok(client.post(f"/api/patients/{patient['id']}/encounters",
                               json={"encounter_type": "OPD", "reason": "Fever"}), 201)
    return {"patient": patient, "encounter": encounter}


def as_(auth_client, user, method, path, body=None):
    return auth_client.request(method, path, json=body, headers=user["headers"])


# --- the same endpoint, different roles --------------------------------------------------------------

MATRIX = [
    # (description, method, path template, body builder, {role: expected status})
    ("register patient", "POST", "/api/patients",
     lambda c: {"first_name": "New", "last_name": f"P{uuid.uuid4().hex[:6]}", "date_of_birth": "1990-01-01", "sex": "MALE"},
     {"DOCTOR": 201, "NURSE": 403, "RECEPTIONIST": 201, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 201}),
    ("view patient", "GET", "/api/patients/{patient}", None,
     {r: 200 for r in ROLES}),
    ("write clinical note", "POST", "/api/patients/{patient}/clinical-notes",
     lambda c: {"encounter_id": c["encounter"]["id"], "note_type": "PROGRESS", "content": "x"},
     {"DOCTOR": 201, "NURSE": 201, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 201}),
    ("read clinical notes", "GET", "/api/patients/{patient}/clinical-notes", None,
     {"DOCTOR": 200, "NURSE": 200, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 200}),
    ("record vitals", "POST", "/api/patients/{patient}/observations",
     lambda c: {"code": "heart_rate", "value_numeric": 80, "unit": "/min", "effective_at": datetime.now(UTC).isoformat()},
     {"DOCTOR": 201, "NURSE": 201, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 201}),
    ("prescribe", "POST", "/api/patients/{patient}/prescriptions",
     lambda c: {"encounter_id": c["encounter"]["id"], "items": [
         {"medicine_name": "Paracetamol", "dose_value": 1, "dose_unit": "g", "route": "ORAL", "frequency": "QID"}]},
     {"DOCTOR": 201, "NURSE": 403, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 201}),
    ("view prescriptions", "GET", "/api/patients/{patient}/prescriptions", None,
     {"DOCTOR": 200, "NURSE": 200, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 200, "SUPER_ADMIN": 200}),
    ("order lab test", "POST", "/api/patients/{patient}/lab-orders",
     lambda c: {"encounter_id": c["encounter"]["id"], "test_code": "fbc", "test_name": "FBC"},
     {"DOCTOR": 201, "NURSE": 403, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 201}),
    ("view lab orders", "GET", "/api/patients/{patient}/lab-orders", None,
     {"DOCTOR": 200, "NURSE": 200, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 200, "PHARMACIST": 403, "SUPER_ADMIN": 200}),
    ("book appointment", "GET", "/api/appointments", None,
     {"DOCTOR": 200, "NURSE": 200, "RECEPTIONIST": 200, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 200}),
    ("manage staff", "POST", "/api/departments", lambda c: {"name": f"Dept {uuid.uuid4().hex[:6]}"},
     {"DOCTOR": 403, "NURSE": 403, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 201}),
    ("list users", "GET", "/api/users", None,
     {"DOCTOR": 403, "NURSE": 403, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 200}),
    ("list roles", "GET", "/api/roles", None,
     {"DOCTOR": 403, "NURSE": 403, "RECEPTIONIST": 403, "LAB_TECHNICIAN": 403, "PHARMACIST": 403, "SUPER_ADMIN": 200}),
]


@pytest.mark.parametrize(("description", "method", "path", "body", "expected"), MATRIX, ids=[m[0] for m in MATRIX])
def test_roles_against_the_same_endpoint(auth_client, users, chart, description, method, path, body, expected):
    url = path.format(patient=chart["patient"]["id"])
    for role, status in expected.items():
        response = as_(auth_client, users[role], method, url, body(chart) if body else None)
        assert response.status_code == status, f"{role} {description}: {response.status_code} {response.text}"
        if status == 403:
            assert response.json()["detail"].startswith("Missing permission:")


def test_denied_calls_change_nothing(auth_client, users, chart, client):
    before = ok(client.get(f"/api/patients/{chart['patient']['id']}"))
    response = as_(auth_client, users["PHARMACIST"], "PATCH", f"/api/patients/{chart['patient']['id']}",
                   {"city": "Hacked"})
    assert response.status_code == 403
    assert ok(client.get(f"/api/patients/{chart['patient']['id']}")) == before


# --- sweep every route: unauthenticated -> 401, authenticated without permission -> 403 ------------------


def all_operations(auth_client):
    schema = auth_client.get("/openapi.json").json()
    for path, operations in schema["paths"].items():
        if not path.startswith("/api") or path == "/api/auth/login":
            continue
        concrete = re.sub(r"\{code\}", "patient.view", path)
        concrete = re.sub(r"\{[a-z_]+\}", str(uuid.uuid4()), concrete)
        for method in operations:
            yield method.upper(), path, concrete


def test_every_route_rejects_unauthenticated_calls(auth_client):
    checked = 0
    for method, path, url in all_operations(auth_client):
        response = auth_client.request(method, url, json={})
        assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
        checked += 1
    assert checked > 100


def test_every_permissioned_route_rejects_a_user_without_roles(auth_client, make_user):
    nobody = make_user()  # a valid account with no roles at all
    self_service = {"/api/auth/me", "/api/auth/logout", "/api/auth/logout-all", "/api/auth/change-password"}
    checked = 0
    for method, path, url in all_operations(auth_client):
        if path in self_service:
            continue
        response = auth_client.request(method, url, json={}, headers=nobody["headers"])
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"
        checked += 1
    assert checked > 100


def test_forged_and_tampered_tokens(auth_client, make_user):
    u = make_user("SUPER_ADMIN")
    tampered = u["token"][:-2] + ("AA" if not u["token"].endswith("AA") else "BB")
    for token in (tampered, u["token"] + "x", u["token"].upper(), "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9."):
        assert auth_client.get("/api/users", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_query_and_body_cannot_smuggle_identity(auth_client, users):
    r = users["RECEPTIONIST"]
    assert auth_client.get("/api/users", params={"user_id": users["SUPER_ADMIN"]["user"]["id"], "role": "SUPER_ADMIN"},
                           headers=r["headers"]).status_code == 403
    assert auth_client.get("/api/users", headers={**r["headers"], "X-User-Role": "SUPER_ADMIN",
                                                  "X-Forwarded-User": "admin"}).status_code == 403


# --- dynamic changes take effect immediately ----------------------------------------------------------------


def test_custom_role_grants_and_revokes_in_real_time(client, auth_client, make_user, chart):
    triage = ok(client.post("/api/roles", json={"name": "TRIAGE", "description": "Triage desk",
                                               "permissions": [{"code": "patient.view"}]}), 201)
    u = make_user("TRIAGE")
    url = f"/api/patients/{chart['patient']['id']}/observations"
    body = {"code": "heart_rate", "value_numeric": 90, "unit": "/min", "effective_at": datetime.now(UTC).isoformat()}
    assert as_(auth_client, u, "POST", url, body).status_code == 403
    ok(client.post(f"/api/roles/{triage['id']}/permissions", json={"code": "observation.create"}))
    assert as_(auth_client, u, "POST", url, body).status_code == 201  # same token, new permission
    ok(client.delete(f"/api/roles/{triage['id']}/permissions/observation.create"))
    assert as_(auth_client, u, "POST", url, body).status_code == 403


def test_deactivated_role_stops_granting(client, auth_client, users, chart):
    doctor = users["DOCTOR"]
    url = f"/api/patients/{chart['patient']['id']}/clinical-notes"
    ok(as_(auth_client, doctor, "GET", url))
    role_id = next(r["id"] for r in doctor["user"]["roles"] if r["name"] == "DOCTOR")
    ok(client.post(f"/api/roles/{role_id}/deactivate"))
    assert as_(auth_client, doctor, "GET", url).status_code == 403
    ok(client.post(f"/api/roles/{role_id}/reactivate"))
    ok(as_(auth_client, doctor, "GET", url))


def test_removing_a_role_takes_effect_on_existing_token(client, auth_client, users):
    doctor = users["DOCTOR"]
    role_id = next(r["id"] for r in doctor["user"]["roles"] if r["name"] == "DOCTOR")
    ok(as_(auth_client, doctor, "GET", "/api/staff"))
    ok(client.delete(f"/api/users/{doctor['user']['id']}/roles/{role_id}"))
    assert as_(auth_client, doctor, "GET", "/api/staff").status_code == 403


# --- resource scope ----------------------------------------------------------------------------------------


def test_own_scope_limits_nurses_to_their_tasks(client, auth_client, make_user, make_department, chart):
    ward = make_department(name="Ward")
    nurse_a, nurse_b = make_user("NURSE", department=ward), make_user("NURSE", department=ward)
    doctor = make_user("DOCTOR", department=ward)
    mine = ok(client.post("/api/workflow-tasks", json={"workflow_type": "NURSING_CARE", "title": "mine",
                                                       "assigned_staff_id": nurse_a["staff"]["id"]}), 201)
    theirs = ok(client.post("/api/workflow-tasks", json={"workflow_type": "NURSING_CARE", "title": "theirs",
                                                         "assigned_staff_id": nurse_b["staff"]["id"]}), 201)
    ok(client.post("/api/workflow-tasks", json={"workflow_type": "OTHER", "title": "unassigned"}), 201)

    listed = ok(as_(auth_client, nurse_a, "GET", "/api/workflow-tasks"))
    assert [t["id"] for t in listed["items"]] == [mine["id"]]
    peek = ok(as_(auth_client, nurse_a, "GET", f"/api/workflow-tasks?assigned_staff_id={nurse_b['staff']['id']}"))
    assert peek["items"] == [] and peek["total"] == 0
    assert as_(auth_client, nurse_a, "GET", f"/api/workflow-tasks/{theirs['id']}").status_code == 404
    assert as_(auth_client, nurse_a, "POST", f"/api/workflow-tasks/{theirs['id']}/start").status_code == 404
    ok(as_(auth_client, nurse_a, "POST", f"/api/workflow-tasks/{mine['id']}/start"))
    ok(as_(auth_client, nurse_a, "POST", f"/api/workflow-tasks/{mine['id']}/complete", {"completion_notes": "done"}))
    # OWN scope cannot create or (re)assign work.
    assert as_(auth_client, nurse_a, "POST", "/api/workflow-tasks",
               {"workflow_type": "OTHER", "title": "x", "assigned_staff_id": nurse_a["staff"]["id"]}).status_code == 403
    assert as_(auth_client, nurse_a, "POST", f"/api/workflow-tasks/{theirs['id']}/assign",
               {"staff_id": nurse_a["staff"]["id"]}).status_code == 403
    # ALL scope (doctor) sees everything.
    assert ok(as_(auth_client, doctor, "GET", "/api/workflow-tasks"))["total"] == 3


def test_timeline_only_shows_permitted_event_types(client, auth_client, make_user, chart):
    patient_id = chart["patient"]["id"]
    ok(client.post(f"/api/patients/{patient_id}/prescriptions", json={
        "encounter_id": chart["encounter"]["id"], "prescriber_name": "x", "items": [
            {"medicine_name": "Paracetamol", "dose_value": 1, "dose_unit": "g", "route": "ORAL", "frequency": "QID"}]}), 201)
    rx = ok(client.get(f"/api/patients/{patient_id}/prescriptions"))["items"][0]
    ok(client.post(f"/api/prescriptions/{rx['id']}/activate"))
    # Clinical reads also need patient.view at ALL scope (see requires_clinical_read).
    ok(client.post("/api/roles", json={"name": "TIMELINE_ONLY", "permissions": [
        {"code": "timeline.view"}, {"code": "patient.view"}]}), 201)
    ok(client.post("/api/roles", json={"name": "TIMELINE_RX", "permissions": [
        {"code": "timeline.view"}, {"code": "patient.view"}, {"code": "prescription.view"}]}), 201)
    doctor, only, rx_viewer = make_user("DOCTOR"), make_user("TIMELINE_ONLY"), make_user("TIMELINE_RX")
    kinds = lambda u: [e["event_type"] for e in ok(as_(auth_client, u, "GET", f"/api/patients/{patient_id}/timeline"))["items"]]
    assert sorted(kinds(doctor)) == ["encounter", "prescription"]
    assert kinds(only) == []
    assert kinds(rx_viewer) == ["prescription"]
    assert as_(auth_client, make_user("RECEPTIONIST"), "GET", f"/api/patients/{patient_id}/timeline").status_code == 403


# --- staff references are preserved --------------------------------------------------------------------


def test_logged_in_staff_can_sign_records_with_their_staff_id(auth_client, users, chart):
    doctor = users["DOCTOR"]
    note = ok(as_(auth_client, doctor, "POST", f"/api/patients/{chart['patient']['id']}/clinical-notes", {
        "encounter_id": chart["encounter"]["id"], "note_type": "PROGRESS", "content": "Seen",
        "author_staff_id": doctor["staff"]["id"]}), 201)
    assert note["author_staff_id"] == doctor["staff"]["id"]


def test_health_endpoints_stay_public(auth_client):
    assert auth_client.get("/health").status_code == 200
    assert auth_client.get("/health/db").status_code == 200


def test_openapi_declares_bearer_security(auth_client):
    schema = auth_client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert "security" in schema["paths"]["/api/patients"]["get"]
    assert "security" not in schema["paths"]["/api/auth/login"]["post"]


def test_expired_session_timestamps_are_utc(auth_client, make_user):
    u = make_user("DOCTOR")
    body = ok(auth_client.post("/api/auth/login", json={"username": u["user"]["username"], "password": u["password"]}))
    assert body["expires_at"].endswith("Z") and datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC) + timedelta(hours=1)
