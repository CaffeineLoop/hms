"""Stage 5 authentication against hms_test with real users, passwords and bearer tokens."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core import security
from tests.integration.conftest import strong_password

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def login(auth_client, username, password):
    return auth_client.post("/api/auth/login", json={"username": username, "password": password})


# --- login ---------------------------------------------------------------------------------------


def test_login_success_returns_token_and_profile(auth_client, make_user):
    u = make_user("DOCTOR")
    response = login(auth_client, u["user"]["username"], u["password"])
    body = ok(response)
    assert body["token_type"] == "bearer" and len(body["access_token"]) >= 43
    assert response.headers["Cache-Control"] == "no-store"
    assert body["user"]["username"] == u["user"]["username"] and body["user"]["roles"] == ["DOCTOR"]
    assert body["user"]["staff"]["id"] == u["staff"]["id"] and body["user"]["is_superuser"] is False
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=7) < expires - datetime.now(UTC) <= timedelta(hours=8, minutes=1)


def test_login_is_case_insensitive_for_username(auth_client, make_user):
    u = make_user("NURSE")
    ok(login(auth_client, u["user"]["username"].upper(), u["password"]))


@pytest.mark.parametrize("case", ["wrong_password", "unknown_user", "empty_password_case"])
def test_login_failures_are_indistinguishable(auth_client, make_user, case):
    u = make_user("DOCTOR")
    username, password = u["user"]["username"], u["password"]
    if case == "wrong_password":
        password = password + "x"
    elif case == "unknown_user":
        username = "nobody-here"
    else:
        password = password.upper()
    response = login(auth_client, username, password)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid username or password."}
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_inactive_user_and_inactive_staff_cannot_log_in(client, auth_client, make_user):
    a, b = make_user("DOCTOR"), make_user("NURSE")
    ok(client.post(f"/api/users/{a['user']['id']}/deactivate"))
    ok(client.post(f"/api/staff/{b['staff']['id']}/deactivate"))
    for u in (a, b):
        response = login(auth_client, u["user"]["username"], u["password"])
        assert response.status_code == 401 and response.json()["detail"] == "Invalid username or password."


def test_login_validation(auth_client):
    assert auth_client.post("/api/auth/login", json={}).status_code == 422
    assert auth_client.post("/api/auth/login", json={"username": "a", "password": ""}).status_code == 422
    assert auth_client.post("/api/auth/login", json={"username": "a", "password": "x", "extra": 1}).status_code == 422


def test_passwords_are_never_stored_or_returned_in_plaintext(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    with test_engine.connect() as connection:
        stored = connection.execute(text("SELECT password_hash FROM users WHERE id = :i"), {"i": u["user"]["id"]}).scalar_one()
        tokens = connection.execute(text("SELECT token_hash FROM auth_sessions WHERE user_id = :i"),
                                    {"i": u["user"]["id"]}).scalars().all()
    assert stored.startswith("scrypt$") and u["password"] not in stored
    assert u["token"] not in tokens and security.token_digest(u["token"]) in tokens
    me = auth_client.get("/api/auth/me", headers=u["headers"]).text
    assert "password" not in me and "scrypt" not in me


def test_weak_hash_is_upgraded_on_login(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    salt = b"fedcba9876543210"
    weak = f"scrypt$10$8$1${security._b64(salt)}${security._b64(security._derive(u['password'], salt, 10, 8, 1))}"
    with test_engine.begin() as connection:
        connection.execute(text("UPDATE users SET password_hash = :h WHERE id = :i"), {"h": weak, "i": u["user"]["id"]})
    ok(login(auth_client, u["user"]["username"], u["password"]))
    with test_engine.connect() as connection:
        upgraded = connection.execute(text("SELECT password_hash FROM users WHERE id = :i"),
                                      {"i": u["user"]["id"]}).scalar_one()
    assert upgraded.startswith("scrypt$14$8$5$")


# --- tokens -------------------------------------------------------------------------------------


def test_current_user(auth_client, make_user):
    u = make_user("NURSE")
    me = ok(auth_client.get("/api/auth/me", headers=u["headers"]))
    codes = {g["code"]: g["scope"] for g in me["permissions"]}
    assert me["roles"] == ["NURSE"] and codes["observation.create"] == "ALL" and codes["workflow.view"] == "OWN"
    assert "prescription.create" not in codes


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer not-a-real-token"},
    {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Token abc"},
])
def test_missing_or_invalid_tokens_are_401(auth_client, headers):
    response = auth_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401 and response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_is_401(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    with test_engine.begin() as connection:
        connection.execute(text("UPDATE auth_sessions SET created_at = now() - interval '2 days', "
                                "expires_at = now() - interval '1 second' WHERE user_id = :i"), {"i": u["user"]["id"]})
    response = auth_client.get("/api/auth/me", headers=u["headers"])
    assert response.status_code == 401 and response.json() == {"detail": "Invalid or expired token."}


def test_token_of_deactivated_user_or_staff_stops_working_immediately(client, auth_client, make_user):
    a, b = make_user("DOCTOR"), make_user("DOCTOR")
    ok(auth_client.get("/api/auth/me", headers=a["headers"]))
    ok(client.post(f"/api/users/{a['user']['id']}/deactivate"))
    ok(client.post(f"/api/staff/{b['staff']['id']}/deactivate"))
    assert auth_client.get("/api/auth/me", headers=a["headers"]).status_code == 401
    assert auth_client.get("/api/auth/me", headers=b["headers"]).status_code == 401
    ok(client.post(f"/api/users/{a['user']['id']}/reactivate"))
    assert auth_client.get("/api/auth/me", headers=a["headers"]).status_code == 401  # sessions were revoked


def test_logout_revokes_only_this_token(auth_client, make_user):
    u = make_user("DOCTOR")
    second = ok(login(auth_client, u["user"]["username"], u["password"]))["access_token"]
    assert auth_client.post("/api/auth/logout", headers=u["headers"]).status_code == 204
    assert auth_client.get("/api/auth/me", headers=u["headers"]).status_code == 401
    assert auth_client.post("/api/auth/logout", headers=u["headers"]).status_code == 401
    ok(auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {second}"}))


def test_logout_all(auth_client, make_user):
    u = make_user("DOCTOR")
    second = ok(login(auth_client, u["user"]["username"], u["password"]))["access_token"]
    assert auth_client.post("/api/auth/logout-all", headers=u["headers"]).status_code == 204
    for token in (u["token"], second):
        assert auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_token_expiry_follows_configuration(test_settings, migrated_database, make_user):
    from fastapi.testclient import TestClient

    from app.factory import create_app

    u = make_user("DOCTOR")
    short = test_settings.model_copy(update={"auth_token_ttl_minutes": 5})
    with TestClient(create_app(short)) as client:
        body = ok(login(client, u["user"]["username"], u["password"]))
    remaining = datetime.fromisoformat(body["expires_at"]) - datetime.now(UTC)
    assert timedelta(minutes=4) < remaining <= timedelta(minutes=5)


# --- change password ---------------------------------------------------------------------------------


def test_change_password(auth_client, make_user):
    u = make_user("DOCTOR")
    other_session = ok(login(auth_client, u["user"]["username"], u["password"]))["access_token"]
    new = strong_password()
    body = {"current_password": u["password"], "new_password": new}
    assert auth_client.post("/api/auth/change-password", json=body, headers=u["headers"]).status_code == 204
    ok(auth_client.get("/api/auth/me", headers=u["headers"]))  # the current session survives
    assert auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {other_session}"}).status_code == 401
    assert login(auth_client, u["user"]["username"], u["password"]).status_code == 401
    ok(login(auth_client, u["user"]["username"], new))


def test_change_password_rejections(auth_client, make_user):
    u = make_user("DOCTOR")
    url, h = "/api/auth/change-password", u["headers"]
    wrong = auth_client.post(url, json={"current_password": u["password"] + "x", "new_password": strong_password()},
                             headers=h)
    assert wrong.status_code == 422 and wrong.json()["detail"][0]["loc"] == ["body", "current_password"]
    weak = auth_client.post(url, json={"current_password": u["password"], "new_password": "short"}, headers=h)
    assert weak.status_code == 422
    with_name = auth_client.post(url, json={"current_password": u["password"],
                                            "new_password": f"X9-{u['user']['username']}-long"}, headers=h)
    assert with_name.status_code == 422
    assert auth_client.post(url, json={"current_password": u["password"], "new_password": strong_password()}
                            ).status_code == 401


# --- bootstrap CLI ------------------------------------------------------------------------------------


def test_cli_create_admin(test_engine, auth_client, clean_patients):
    from app.cli import create_admin
    from app.db.session import build_session_factory

    password = strong_password()
    with build_session_factory(test_engine)() as session:
        user = create_admin(session, username="root.admin", employee_code="ADM-0001", first_name="Root",
                            last_name="Admin", password=password)
        assert user.password_hash.startswith("scrypt$")
    body = ok(login(auth_client, "root.admin", password))
    assert body["user"]["is_superuser"] is True and body["user"]["roles"] == ["SUPER_ADMIN"]
    with build_session_factory(test_engine)() as session, pytest.raises(SystemExit, match="already exists"):
        create_admin(session, username="root.admin", employee_code="ADM-0002", first_name="R", last_name="A",
                     password=password)


def test_cli_rejects_weak_password_from_environment(monkeypatch):
    from app.cli import _read_password

    monkeypatch.setenv("HMS_ADMIN_PASSWORD", "weak")
    with pytest.raises(SystemExit, match="Password rejected"):
        _read_password("admin")
