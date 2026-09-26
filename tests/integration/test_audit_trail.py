"""Stage 6 audit trail: what is recorded, attribution, access control, immutability, no secrets."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.conftest import strong_password

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@pytest.fixture
def since(test_engine):
    with test_engine.connect() as c:
        return c.execute(text("SELECT clock_timestamp()")).scalar_one()


@pytest.fixture
def events(test_engine, since):
    """Audit rows written since the test started, oldest first, as dicts."""

    def fetch(**filters) -> list[dict]:
        clauses = " ".join(f"AND {k} = :{k}" for k in filters)
        with test_engine.connect() as c:
            rows = c.execute(text(f"SELECT * FROM audit_events WHERE occurred_at >= :since {clauses} "
                                  "ORDER BY occurred_at, id"), {"since": since, **filters}).mappings().all()
        return [dict(r) for r in rows]

    return fetch


def as_(auth_client, user, method, path, body=None):
    return auth_client.request(method, path, json=body, headers=user["headers"])


# --- authentication events ----------------------------------------------------------------------


def test_login_success_and_failure_are_audited_without_secrets(auth_client, make_user, events):
    u = make_user("DOCTOR")  # includes one successful login
    wrong = u["password"] + "x"
    assert auth_client.post("/api/auth/login", json={"username": u["user"]["username"], "password": wrong}).status_code == 401
    assert auth_client.post("/api/auth/login", json={"username": "ghost.user", "password": wrong}).status_code == 401
    logins = events(action="auth.login")
    success, bad_password, unknown = logins[-3], logins[-2], logins[-1]
    assert success["outcome"] == "SUCCESS" and success["actor_user_id"] is not None
    assert success["resource_type"] == "sessions" and success["session_id"] is not None
    assert bad_password["outcome"] == "FAILURE" and bad_password["details"] == {"reason": "bad_password"}
    assert str(bad_password["actor_user_id"]) == u["user"]["id"]
    assert unknown["outcome"] == "FAILURE" and unknown["actor_user_id"] is None
    assert unknown["actor_username"] == "ghost.user" and unknown["details"] == {"reason": "unknown_user"}
    dump = json.dumps([e for e in events()], default=str)
    assert u["password"] not in dump and wrong not in dump and u["token"] not in dump


def test_logout_logout_all_and_password_change_are_audited(auth_client, make_user, events):
    u = make_user("NURSE")
    new = strong_password()
    body = {"current_password": u["password"] + "x", "new_password": new}
    assert auth_client.post("/api/auth/change-password", json=body, headers=u["headers"]).status_code == 422
    body["current_password"] = u["password"]
    assert auth_client.post("/api/auth/change-password", json=body, headers=u["headers"]).status_code == 204
    assert auth_client.post("/api/auth/logout-all", headers=u["headers"]).status_code == 204
    changes = events(action="auth.password_change")
    assert [c["outcome"] for c in changes] == ["FAILURE", "SUCCESS"]
    assert changes[0]["details"] == {"reason": "current_password_incorrect"}
    assert events(action="auth.logout_all")[0]["details"]["sessions_revoked"] >= 1
    other = auth_client.post("/api/auth/login", json={"username": u["user"]["username"], "password": new}).json()
    auth_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {other['access_token']}"})
    [logout] = events(action="auth.logout")
    assert logout["outcome"] == "SUCCESS" and str(logout["actor_user_id"]) == u["user"]["id"]
    assert new not in json.dumps(events(), default=str)


# --- RBAC / administration events ------------------------------------------------------------------


def test_rbac_changes_are_audited_with_actor_and_metadata(auth_client, make_user, make_staff, events):
    admin = make_user("SUPER_ADMIN")
    role = ok(as_(auth_client, admin, "POST", "/api/roles", {"name": "AUDIT_PROBE",
                                                             "permissions": [{"code": "patient.view"}]}), 201)
    ok(as_(auth_client, admin, "PATCH", f"/api/roles/{role['id']}", {"description": "changed"}))
    ok(as_(auth_client, admin, "POST", f"/api/roles/{role['id']}/permissions", {"code": "encounter.view"}))
    ok(as_(auth_client, admin, "DELETE", f"/api/roles/{role['id']}/permissions/encounter.view"))
    staff = make_staff()
    password = strong_password()
    user = ok(as_(auth_client, admin, "POST", "/api/users", {"staff_id": staff["id"], "username": "probe.user",
                                                             "password": password}), 201)
    ok(as_(auth_client, admin, "POST", f"/api/users/{user['id']}/roles", {"role_id": role["id"]}))
    ok(as_(auth_client, admin, "DELETE", f"/api/users/{user['id']}/roles/{role['id']}"))
    ok(as_(auth_client, admin, "POST", f"/api/users/{user['id']}/reset-password", {"new_password": strong_password()}))
    ok(as_(auth_client, admin, "POST", f"/api/users/{user['id']}/deactivate"))
    ok(as_(auth_client, admin, "POST", f"/api/roles/{role['id']}/deactivate"))

    # Only the admin's own actions (fixtures also create accounts, which are audited too).
    recorded = [e for e in events() if e["action"].startswith(("role.", "user."))
                and str(e["actor_user_id"]) == admin["user"]["id"]]
    assert [e["action"] for e in recorded] == [
        "role.create", "role.update", "role.permission_grant", "role.permission_revoke", "user.create",
        "user.role_assign", "user.role_remove", "user.password_reset", "user.deactivate", "role.deactivate"]
    assert all(e["outcome"] == "SUCCESS" and str(e["actor_user_id"]) == admin["user"]["id"] for e in recorded)
    by_action = {e["action"]: e for e in recorded}
    assert by_action["role.create"]["details"]["permissions"] == ["patient.view:ALL"]
    assert by_action["role.permission_grant"]["details"]["permission"] == "encounter.view"
    assert by_action["user.role_assign"]["details"]["role"] == "AUDIT_PROBE"
    assert by_action["role.update"]["details"]["changes"]["description"]["to"] == "changed"
    assert password not in json.dumps(recorded, default=str)


def test_denied_escalation_attempts_are_audited(auth_client, make_user, events):
    doctor = make_user("DOCTOR")
    assert as_(auth_client, doctor, "POST", "/api/roles", {"name": "EVIL"}).status_code == 403
    [denied] = events(action="POST /api/roles")
    assert denied["outcome"] == "DENIED" and denied["status_code"] == 403
    assert str(denied["actor_user_id"]) == doctor["user"]["id"]


def test_unauthenticated_attempts_are_audited(auth_client, events):
    assert auth_client.get("/api/patients").status_code == 401
    [event] = events(action="GET /api/patients")
    assert event["outcome"] == "DENIED" and event["status_code"] == 401 and event["actor_user_id"] is None
    assert event["client_ip"] and event["request_id"]


# --- clinical mutations and sensitive reads ---------------------------------------------------------


def test_clinical_mutation_and_patient_access_are_audited(auth_client, make_user, events):
    doctor = make_user("DOCTOR")
    patient = ok(as_(auth_client, doctor, "POST", "/api/patients", {
        "first_name": "Audit", "last_name": "Subject", "date_of_birth": "1980-01-01", "sex": "FEMALE"}), 201)
    encounter = ok(as_(auth_client, doctor, "POST", f"/api/patients/{patient['id']}/encounters",
                       {"encounter_type": "OPD", "reason": "Review"}), 201)
    note = ok(as_(auth_client, doctor, "POST", f"/api/patients/{patient['id']}/clinical-notes",
                  {"encounter_id": encounter["id"], "note_type": "PROGRESS", "content": "Sensitive text"}), 201)
    ok(as_(auth_client, doctor, "GET", f"/api/patients/{patient['id']}/timeline"))
    ok(as_(auth_client, doctor, "GET", f"/api/patients?q={patient['last_name']}"))

    [created] = events(action="POST /api/patients/{patient_id}/clinical-notes")
    assert created["outcome"] == "SUCCESS" and created["resource_type"] == "clinical-notes"
    assert created["resource_id"] == note["id"] and str(created["patient_id"]) == patient["id"]
    assert str(created["actor_staff_id"]) == doctor["staff"]["id"] and created["status_code"] == 201
    [read] = events(action="GET /api/patients/{patient_id}/timeline")
    assert str(read["patient_id"]) == patient["id"] and read["http_method"] == "GET"
    [search] = events(action="GET /api/patients")
    assert "q=" not in (search["route"] or "")  # query strings (patient names) are never stored
    dump = json.dumps(events(), default=str)
    assert "Sensitive text" not in dump and "Subject" not in dump


def test_failed_mutations_are_audited_as_failures(auth_client, make_user, events):
    doctor = make_user("DOCTOR")
    assert as_(auth_client, doctor, "POST", "/api/patients", {"first_name": ""}).status_code == 422
    [event] = events(action="POST /api/patients")
    assert event["outcome"] == "FAILURE" and event["status_code"] == 422


# --- audit API access / immutability ----------------------------------------------------------------


def test_audit_trail_requires_audit_view(client, auth_client, make_user):
    doctor, admin = make_user("DOCTOR"), make_user("SUPER_ADMIN")
    assert as_(auth_client, doctor, "GET", "/api/audit-events").status_code == 403
    ok(client.post("/api/roles", json={"name": "AUDITOR", "permissions": [{"code": "audit.view"}]}), 201)
    auditor = make_user("AUDITOR")
    for user in (admin, auditor):
        body = ok(as_(auth_client, user, "GET", "/api/audit-events"))
        assert body["total"] >= 1 and body["items"][0]["occurred_at"] >= body["items"][-1]["occurred_at"]
    one = ok(as_(auth_client, auditor, "GET", "/api/audit-events", None))["items"][0]
    assert ok(as_(auth_client, auditor, "GET", f"/api/audit-events/{one['id']}"))["id"] == one["id"]
    assert as_(auth_client, auditor, "GET", "/api/audit-events/00000000-0000-0000-0000-000000000000").status_code == 404


def test_audit_search_filters(auth_client, make_user, since):
    admin, doctor = make_user("SUPER_ADMIN"), make_user("DOCTOR")
    patient = ok(as_(auth_client, doctor, "POST", "/api/patients", {
        "first_name": "Filter", "last_name": "Case", "date_of_birth": "1970-01-01", "sex": "MALE"}), 201)
    ok(as_(auth_client, doctor, "GET", f"/api/patients/{patient['id']}"))
    params = {"patient_id": patient["id"], "occurred_from": since.isoformat()}
    by_patient = auth_client.get("/api/audit-events", params=params, headers=admin["headers"]).json()
    # Both the registration (id taken from the Location header) and the read are tied to the patient.
    assert {e["action"] for e in by_patient["items"]} == {"POST /api/patients", "GET /api/patients/{patient_id}"}
    mine = auth_client.get("/api/audit-events", params={"actor_user_id": doctor["user"]["id"], "action": "auth.login"},
                           headers=admin["headers"]).json()
    assert mine["total"] == 1 and mine["items"][0]["outcome"] == "SUCCESS"
    assert auth_client.get("/api/audit-events", params={"outcome": "MAYBE"}, headers=admin["headers"]).status_code == 422


def test_audit_trail_has_no_write_api(auth_client, make_user):
    admin = make_user("SUPER_ADMIN")
    one = auth_client.get("/api/audit-events", headers=admin["headers"]).json()["items"][0]
    for method, path in (("POST", "/api/audit-events"), ("PUT", f"/api/audit-events/{one['id']}"),
                         ("PATCH", f"/api/audit-events/{one['id']}"), ("DELETE", f"/api/audit-events/{one['id']}")):
        assert auth_client.request(method, path, json={}, headers=admin["headers"]).status_code == 405


@pytest.mark.parametrize("statement", [
    "UPDATE audit_events SET outcome = 'SUCCESS'",
    "DELETE FROM audit_events",
    "TRUNCATE audit_events",
])
def test_audit_rows_cannot_be_modified_in_the_database(test_engine, statement):
    with test_engine.begin() as c:
        c.execute(text("INSERT INTO audit_events (action, outcome) VALUES ('immutability.probe', 'FAILURE')"))
    with pytest.raises(DBAPIError, match="append-only"):
        with test_engine.begin() as c:
            c.execute(text(statement))
    with test_engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM audit_events WHERE action = 'immutability.probe'")).scalar_one() >= 1


def test_audit_timestamps_are_utc(auth_client, make_user):
    admin = make_user("SUPER_ADMIN")
    newest = auth_client.get("/api/audit-events", headers=admin["headers"]).json()["items"][0]
    assert newest["occurred_at"].endswith("Z")
    assert abs(datetime.fromisoformat(newest["occurred_at"]) - datetime.now(UTC)).total_seconds() < 120
