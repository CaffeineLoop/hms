"""Stage 6 session hardening: idle timeout, revocation reasons, invalidation, no token leakage."""

import logging

import pytest
from sqlalchemy import text

from app.core import security
from tests.integration.conftest import strong_password

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def session_row(test_engine, token: str) -> dict:
    with test_engine.connect() as c:
        return dict(c.execute(text("SELECT * FROM auth_sessions WHERE token_hash = :h"),
                              {"h": security.token_digest(token)}).mappings().one())


def age_last_seen(test_engine, token: str, interval: str) -> None:
    with test_engine.begin() as c:
        c.execute(text(f"UPDATE auth_sessions SET last_seen_at = now() - interval '{interval}' WHERE token_hash = :h"),
                  {"h": security.token_digest(token)})


def test_idle_session_is_revoked(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    age_last_seen(test_engine, u["token"], "31 minutes")  # default idle timeout: 30 minutes
    response = auth_client.get("/api/auth/me", headers=u["headers"])
    assert response.status_code == 401 and response.json() == {"detail": "Invalid or expired token."}
    row = session_row(test_engine, u["token"])
    assert row["revoked_at"] is not None and row["revocation_reason"] == "IDLE_TIMEOUT"
    with test_engine.connect() as c:
        event = c.execute(text("SELECT details FROM audit_events WHERE action = 'auth.session_revoked' "
                               "AND session_id = :s"), {"s": row["id"]}).scalar_one()
    assert event == {"reason": "IDLE_TIMEOUT"}
    assert auth_client.get("/api/auth/me", headers=u["headers"]).status_code == 401  # stays revoked


def test_activity_keeps_session_alive_and_refresh_is_throttled(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    age_last_seen(test_engine, u["token"], "29 minutes")
    ok(auth_client.get("/api/auth/me", headers=u["headers"]))
    first = session_row(test_engine, u["token"])["last_seen_at"]
    ok(auth_client.get("/api/auth/me", headers=u["headers"]))  # within 60 s: no write
    assert session_row(test_engine, u["token"])["last_seen_at"] == first
    age_last_seen(test_engine, u["token"], "20 minutes")
    ok(auth_client.get("/api/auth/me", headers=u["headers"]))
    assert session_row(test_engine, u["token"])["last_seen_at"] > first


def test_absolute_expiry_still_applies(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    with test_engine.begin() as c:
        c.execute(text("UPDATE auth_sessions SET created_at = now() - interval '2 days', "
                       "expires_at = now() - interval '1 second' WHERE token_hash = :h"),
                  {"h": security.token_digest(u["token"])})
    assert auth_client.get("/api/auth/me", headers=u["headers"]).status_code == 401


def login(auth_client, u, password=None):
    return ok(auth_client.post("/api/auth/login", json={"username": u["user"]["username"],
                                                        "password": password or u["password"]}))["access_token"]


def test_every_revocation_records_its_reason(client, auth_client, make_user, test_engine):
    a, b, c_, d, e = (make_user("DOCTOR") for _ in range(5))
    assert auth_client.post("/api/auth/logout", headers=a["headers"]).status_code == 204
    b2 = login(auth_client, b)
    assert auth_client.post("/api/auth/logout-all", headers=b["headers"]).status_code == 204
    c2 = login(auth_client, c_)
    ok(auth_client.post("/api/auth/change-password", headers=c_["headers"],
                        json={"current_password": c_["password"], "new_password": strong_password()}), 204)
    ok(client.post(f"/api/users/{d['user']['id']}/deactivate"))
    ok(client.post(f"/api/staff/{e['staff']['id']}/deactivate"))
    expected = {a["token"]: "LOGOUT", b["token"]: "LOGOUT_ALL", b2: "LOGOUT_ALL", c2: "PASSWORD_CHANGE",
                d["token"]: "USER_DEACTIVATED", e["token"]: "STAFF_DEACTIVATED"}
    for token, reason in expected.items():
        assert session_row(test_engine, token)["revocation_reason"] == reason
        assert auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert session_row(test_engine, c_["token"])["revoked_at"] is None  # the session that changed the password
    ok(auth_client.get("/api/auth/me", headers=c_["headers"]))


def test_password_reset_revokes_all_sessions(client, auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    second = login(auth_client, u)
    ok(client.post(f"/api/users/{u['user']['id']}/reset-password", json={"new_password": strong_password()}))
    for token in (u["token"], second):
        assert session_row(test_engine, token)["revocation_reason"] == "PASSWORD_RESET"


def test_revocation_reason_consistency_is_enforced_in_db(auth_client, make_user, test_engine):
    u = make_user("DOCTOR")
    from sqlalchemy.exc import IntegrityError

    for sql in ("UPDATE auth_sessions SET revoked_at = now() WHERE token_hash = :h",
                "UPDATE auth_sessions SET revocation_reason = 'LOGOUT' WHERE token_hash = :h",
                "UPDATE auth_sessions SET revoked_at = now(), revocation_reason = 'BORED' WHERE token_hash = :h"):
        with pytest.raises(IntegrityError, match="ck_auth_sessions_revocation_matches_reason"):
            with test_engine.begin() as c:
                c.execute(text(sql), {"h": security.token_digest(u["token"])})


def test_tokens_and_passwords_are_never_logged_or_echoed(auth_client, make_user, caplog):
    with caplog.at_level(logging.DEBUG):
        u = make_user("DOCTOR")
        me = auth_client.get("/api/auth/me", headers=u["headers"])
        auth_client.post("/api/auth/login", json={"username": u["user"]["username"], "password": u["password"] + "x"})
        auth_client.post("/api/auth/logout", headers=u["headers"])
    logged = caplog.text
    assert u["token"] not in logged and u["password"] not in logged
    assert security.token_digest(u["token"]) not in logged
    assert u["token"] not in me.text and "token" not in me.json()
    assert me.headers["Cache-Control"] == "no-store"


def test_tokens_are_only_accepted_in_the_authorization_header(auth_client, make_user):
    u = make_user("DOCTOR")
    assert auth_client.get(f"/api/auth/me?access_token={u['token']}").status_code == 401
    assert auth_client.get("/api/auth/me", headers={"Cookie": f"access_token={u['token']}"}).status_code == 401
    assert auth_client.get("/api/auth/me", headers={"Authorization": f"bearer {u['token']}"}).status_code == 200
