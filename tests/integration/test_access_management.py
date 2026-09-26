"""Stage 5 user/role/permission administration and anti-escalation, with real admins and tokens."""

import uuid

import pytest
from sqlalchemy import text

from app.core.permissions import DEFAULT_ROLES, DESCRIPTIONS, P
from tests.integration.conftest import strong_password

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def call(auth_client, user, method, path, body=None, params=None):
    return auth_client.request(method, path, json=body, params=params, headers=user["headers"])


def role_id(auth_client, admin, name: str) -> str:
    roles = ok(call(auth_client, admin, "GET", "/api/roles", params={"limit": 100}))["items"]
    return next(r["id"] for r in roles if r["name"] == name)


@pytest.fixture
def admin(make_user) -> dict:
    return make_user("SUPER_ADMIN")


@pytest.fixture
def user_admin(client, make_user) -> dict:
    """A delegated administrator: DOCTOR-level clinical permissions plus user/role/permission management."""
    doctor_grants = [{"code": c.value, "scope": s.value} for c, s in DEFAULT_ROLES["DOCTOR"][1].items()]
    ok(client.post("/api/roles", json={"name": "USER_ADMIN", "permissions": doctor_grants + [
        {"code": "user.view"}, {"code": "user.manage"}, {"code": "role.manage"}, {"code": "permission.manage"}]}), 201)
    return make_user("USER_ADMIN")


# --- catalog / seeds -----------------------------------------------------------------------------


def test_permissions_listed_match_code_catalog(auth_client, admin):
    listed = ok(call(auth_client, admin, "GET", "/api/permissions"))
    assert {p["code"]: p["description"] for p in listed} == {p.value: DESCRIPTIONS[p] for p in P}


def test_default_roles_are_seeded(auth_client, admin):
    roles = {r["name"]: r for r in ok(call(auth_client, admin, "GET", "/api/roles"))["items"]}
    assert set(roles) == set(DEFAULT_ROLES)
    assert roles["SUPER_ADMIN"]["is_superuser"] and roles["SUPER_ADMIN"]["permissions"] == []
    nurse = {g["code"]: g["scope"] for g in roles["NURSE"]["permissions"]}
    assert nurse == {c.value: s.value for c, s in DEFAULT_ROLES["NURSE"][1].items()}


# --- users ---------------------------------------------------------------------------------------


def test_create_and_manage_user(auth_client, admin, make_staff):
    staff = make_staff(designation="NURSE")
    password = strong_password()
    created = ok(call(auth_client, admin, "POST", "/api/users",
                      {"staff_id": staff["id"], "username": "Jane.Nurse", "password": password}), 201)
    assert created["username"] == "jane.nurse" and created["status"] == "ACTIVE" and created["roles"] == []
    assert "password" not in created and "password_hash" not in created

    nurse_role = role_id(auth_client, admin, "NURSE")
    with_role = ok(call(auth_client, admin, "POST", f"/api/users/{created['id']}/roles", {"role_id": nurse_role}))
    assert [r["name"] for r in with_role["roles"]] == ["NURSE"]
    assert call(auth_client, admin, "POST", f"/api/users/{created['id']}/roles", {"role_id": nurse_role}).status_code == 409
    login = auth_client.post("/api/auth/login", json={"username": "jane.nurse", "password": password})
    assert login.status_code == 200 and login.json()["user"]["roles"] == ["NURSE"]

    without = ok(call(auth_client, admin, "DELETE", f"/api/users/{created['id']}/roles/{nurse_role}"))
    assert without["roles"] == []
    assert call(auth_client, admin, "DELETE", f"/api/users/{created['id']}/roles/{nurse_role}").status_code == 404
    listed = ok(call(auth_client, admin, "GET", "/api/users", params={"q": "jane"}))
    assert [u["username"] for u in listed["items"]] == ["jane.nurse"]


def test_user_creation_conflicts_and_validation(auth_client, admin, make_staff, make_user):
    existing = make_user("NURSE")
    staff = make_staff()
    base = {"staff_id": staff["id"], "username": "fresh.user", "password": strong_password()}
    assert call(auth_client, admin, "POST", "/api/users", {**base, "username": existing["user"]["username"]}).status_code == 409
    assert call(auth_client, admin, "POST", "/api/users", {**base, "staff_id": existing["staff"]["id"]}).status_code == 409
    assert call(auth_client, admin, "POST", "/api/users", {**base, "staff_id": str(uuid.uuid4())}).status_code == 422
    assert call(auth_client, admin, "POST", "/api/users", {**base, "password": "too-short"}).status_code == 422
    assert call(auth_client, admin, "POST", "/api/users", {**base, "role_ids": [str(uuid.uuid4())]}).status_code == 422
    ok(call(auth_client, admin, "POST", f"/api/staff/{staff['id']}/deactivate"))
    assert call(auth_client, admin, "POST", "/api/users", base).status_code == 409


def test_reset_password_revokes_sessions(auth_client, admin, make_user):
    u = make_user("DOCTOR")
    new = strong_password()
    ok(call(auth_client, admin, "POST", f"/api/users/{u['user']['id']}/reset-password", {"new_password": new}))
    assert auth_client.get("/api/auth/me", headers=u["headers"]).status_code == 401
    assert auth_client.post("/api/auth/login", json={"username": u["user"]["username"], "password": new}).status_code == 200


# --- roles -------------------------------------------------------------------------------------------


def test_role_lifecycle(auth_client, admin):
    role = ok(call(auth_client, admin, "POST", "/api/roles", {
        "name": "ward_clerk", "description": "Ward clerk",
        "permissions": [{"code": "patient.view"}, {"code": "workflow.view", "scope": "OWN"}]}), 201)
    assert role["name"] == "WARD_CLERK" and role["user_count"] == 0
    assert {g["code"]: g["scope"] for g in role["permissions"]} == {"patient.view": "ALL", "workflow.view": "OWN"}
    renamed = ok(call(auth_client, admin, "PATCH", f"/api/roles/{role['id']}", {"name": "WARD_SECRETARY"}))
    assert renamed["name"] == "WARD_SECRETARY"
    widened = ok(call(auth_client, admin, "POST", f"/api/roles/{role['id']}/permissions",
                      {"code": "workflow.view", "scope": "ALL"}))
    assert {g["code"]: g["scope"] for g in widened["permissions"]}["workflow.view"] == "ALL"
    assert call(auth_client, admin, "POST", f"/api/roles/{role['id']}/permissions",
                {"code": "workflow.view", "scope": "ALL"}).status_code == 409
    ok(call(auth_client, admin, "DELETE", f"/api/roles/{role['id']}/permissions/workflow.view"))
    assert call(auth_client, admin, "DELETE", f"/api/roles/{role['id']}/permissions/workflow.view").status_code == 404
    assert ok(call(auth_client, admin, "POST", f"/api/roles/{role['id']}/deactivate"))["status"] == "INACTIVE"
    assert call(auth_client, admin, "POST", f"/api/roles/{role['id']}/deactivate").status_code == 409
    ok(call(auth_client, admin, "POST", f"/api/roles/{role['id']}/reactivate"))


def test_role_validation_and_conflicts(auth_client, admin, make_user):
    assert call(auth_client, admin, "POST", "/api/roles", {"name": "DOCTOR"}).status_code == 409
    assert call(auth_client, admin, "POST", "/api/roles", {"name": "bad name"}).status_code == 422
    assert call(auth_client, admin, "POST", "/api/roles",
                {"name": "X_ROLE", "permissions": [{"code": "patient.fly"}]}).status_code == 422
    assert call(auth_client, admin, "POST", "/api/roles",
                {"name": "Y_ROLE", "permissions": [{"code": "patient.view", "scope": "DEPARTMENT"}]}).status_code == 422
    inactive = ok(call(auth_client, admin, "POST", "/api/roles", {"name": "OLD_ROLE"}), 201)
    ok(call(auth_client, admin, "POST", f"/api/roles/{inactive['id']}/deactivate"))
    target = make_user()
    assert call(auth_client, admin, "POST", f"/api/users/{target['user']['id']}/roles",
                {"role_id": inactive["id"]}).status_code == 409


def test_super_admin_system_role_is_locked(auth_client, admin):
    sa = role_id(auth_client, admin, "SUPER_ADMIN")
    assert call(auth_client, admin, "PATCH", f"/api/roles/{sa}", {"name": "ROOT"}).status_code == 409
    assert call(auth_client, admin, "POST", f"/api/roles/{sa}/permissions", {"code": "patient.view"}).status_code == 409
    assert call(auth_client, admin, "POST", f"/api/roles/{sa}/deactivate").status_code == 409
    ok(call(auth_client, admin, "PATCH", f"/api/roles/{sa}", {"description": "Administrators"}))


# --- self-escalation / privilege laundering ----------------------------------------------------------


def test_cannot_change_own_roles(auth_client, admin, user_admin):
    doctor = role_id(auth_client, admin, "DOCTOR")
    me = user_admin["user"]["id"]
    response = call(auth_client, user_admin, "POST", f"/api/users/{me}/roles", {"role_id": doctor})
    assert response.status_code == 403 and "own roles" in response.json()["detail"]
    own_role = user_admin["user"]["roles"][0]["id"]
    assert call(auth_client, user_admin, "DELETE", f"/api/users/{me}/roles/{own_role}").status_code == 403
    assert call(auth_client, admin, "POST", f"/api/users/{admin['user']['id']}/roles", {"role_id": doctor}).status_code == 403


def test_cannot_grant_permissions_to_a_role_you_hold(auth_client, user_admin):
    own_role = user_admin["user"]["roles"][0]["id"]
    response = call(auth_client, user_admin, "POST", f"/api/roles/{own_role}/permissions", {"code": "staff.manage"})
    assert response.status_code == 403 and "role you hold" in response.json()["detail"]
    assert call(auth_client, user_admin, "DELETE", f"/api/roles/{own_role}/permissions/patient.view").status_code == 403
    assert call(auth_client, user_admin, "POST", f"/api/roles/{own_role}/deactivate").status_code == 403


def test_cannot_grant_what_you_do_not_hold(auth_client, user_admin):
    role = ok(call(auth_client, user_admin, "POST", "/api/roles", {"name": "HELPER"}), 201)
    response = call(auth_client, user_admin, "POST", f"/api/roles/{role['id']}/permissions", {"code": "staff.manage"})
    assert response.status_code == 403 and "do not hold" in response.json()["detail"]
    assert call(auth_client, user_admin, "POST", "/api/roles",
                {"name": "SNEAKY", "permissions": [{"code": "audit.view"}]}).status_code == 403
    ok(call(auth_client, user_admin, "POST", f"/api/roles/{role['id']}/permissions", {"code": "patient.view"}))


def test_cannot_launder_privileges_through_role_assignment(auth_client, admin, user_admin, make_user, make_staff):
    colleague = make_user()
    sa = role_id(auth_client, admin, "SUPER_ADMIN")
    response = call(auth_client, user_admin, "POST", f"/api/users/{colleague['user']['id']}/roles", {"role_id": sa})
    assert response.status_code == 403 and "superuser" in response.json()["detail"]
    powerful = ok(call(auth_client, admin, "POST", "/api/roles",
                       {"name": "STAFF_ADMIN", "permissions": [{"code": "staff.manage"}]}), 201)
    response = call(auth_client, user_admin, "POST", f"/api/users/{colleague['user']['id']}/roles",
                    {"role_id": powerful["id"]})
    assert response.status_code == 403 and "staff.manage" in response.json()["detail"]
    # ...nor at account creation (and nothing is created).
    response = call(auth_client, user_admin, "POST", "/api/users", {
        "staff_id": make_staff()["id"], "username": "x.user", "password": strong_password(),
        "role_ids": [powerful["id"]]})
    assert response.status_code == 403
    assert ok(call(auth_client, admin, "GET", "/api/users", params={"q": "x.user"}))["total"] == 0
    # Roles within the delegated admin's own permissions are fine.
    ok(call(auth_client, user_admin, "POST", f"/api/users/{colleague['user']['id']}/roles",
            {"role_id": role_id(auth_client, admin, "DOCTOR")}))


def test_cannot_deactivate_or_reset_self(auth_client, admin):
    me = admin["user"]["id"]
    assert call(auth_client, admin, "POST", f"/api/users/{me}/deactivate").status_code == 403
    assert call(auth_client, admin, "POST", f"/api/users/{me}/reset-password",
                {"new_password": strong_password()}).status_code == 403


def test_last_superuser_is_protected(auth_client, admin, make_user, client):
    second = make_user("SUPER_ADMIN")
    sa = role_id(auth_client, admin, "SUPER_ADMIN")
    ok(call(auth_client, admin, "DELETE", f"/api/users/{second['user']['id']}/roles/{sa}"))  # two -> one: allowed
    assert call(auth_client, second, "POST", f"/api/users/{admin['user']['id']}/deactivate").status_code == 403
    response = client.post(f"/api/staff/{admin['staff']['id']}/deactivate")
    assert response.status_code == 409 and "last active superuser" in response.json()["detail"]
    third = make_user("SUPER_ADMIN")
    response = call(auth_client, third, "DELETE", f"/api/users/{admin['user']['id']}/roles/{sa}")
    assert response.status_code == 200  # third remains, so admin may lose the role
    response = call(auth_client, admin, "POST", f"/api/users/{third['user']['id']}/deactivate")
    assert response.status_code == 403  # admin is no longer a superuser (and lacks user.manage)


def test_management_endpoints_need_management_permissions(auth_client, make_user):
    doctor = make_user("DOCTOR")
    rid = str(uuid.uuid4())
    for method, path, body in [
        ("POST", "/api/roles", {"name": "EVIL"}), ("GET", "/api/permissions", None),
        ("POST", f"/api/roles/{rid}/permissions", {"code": "patient.view"}),
        ("POST", "/api/users", {}), ("GET", "/api/users", None),
        ("POST", f"/api/users/{doctor['user']['id']}/roles", {"role_id": rid}),
    ]:
        assert call(auth_client, doctor, method, path, body).status_code == 403, path


def test_role_manage_without_permission_manage(client, auth_client, make_user):
    ok(client.post("/api/roles", json={"name": "ROLE_CURATOR", "permissions": [{"code": "role.manage"}]}), 201)
    curator = make_user("ROLE_CURATOR")
    role = ok(call(auth_client, curator, "POST", "/api/roles", {"name": "EMPTY_ROLE"}), 201)
    assert call(auth_client, curator, "POST", f"/api/roles/{role['id']}/permissions",
                {"code": "role.manage"}).status_code == 403
    ok(call(auth_client, curator, "GET", "/api/permissions"))


def test_grants_and_assignments_are_attributed(auth_client, admin, make_user, test_engine):
    role = ok(call(auth_client, admin, "POST", "/api/roles",
                   {"name": "AUDITED", "permissions": [{"code": "patient.view"}]}), 201)
    target = make_user()
    ok(call(auth_client, admin, "POST", f"/api/users/{target['user']['id']}/roles", {"role_id": role["id"]}))
    with test_engine.connect() as connection:
        granted_by = connection.execute(text(
            "SELECT granted_by_user_id FROM role_permissions WHERE role_id = :r"), {"r": role["id"]}).scalar_one()
        assigned_by = connection.execute(text(
            "SELECT assigned_by_user_id FROM user_roles WHERE role_id = :r"), {"r": role["id"]}).scalar_one()
    assert str(granted_by) == str(assigned_by) == admin["user"]["id"]
