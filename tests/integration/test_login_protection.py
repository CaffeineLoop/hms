"""Stage 6 login abuse protection: per-username lockout, per-IP limit, no enumeration."""

import secrets
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("clean_patients")]


@pytest.fixture
def limited_app(test_settings, migrated_database):
    """Low limits so lockouts are reachable quickly: 3 per username, 6 per IP, 15-minute window."""
    settings = test_settings.model_copy(update={
        "login_max_failures_per_user": 3, "login_max_failures_per_ip": 6, "login_lockout_minutes": 15})
    return create_app(settings)


@pytest.fixture
def limited(limited_app):
    """A client with a unique IP so tests (and the rest of the suite) never share counters."""
    ip = f"10.{secrets.randbelow(250)}.{secrets.randbelow(250)}.{secrets.randbelow(250) + 1}"
    with TestClient(limited_app, client=(ip, 50000)) as client:
        yield client


def attempt(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_username_is_locked_after_repeated_failures(limited, make_user):
    u = make_user("DOCTOR", username=f"lock.{secrets.token_hex(3)}")
    for _ in range(3):
        assert attempt(limited, u["user"]["username"], u["password"] + "x").status_code == 401
    locked = attempt(limited, u["user"]["username"], u["password"])  # even the correct password
    assert locked.status_code == 429
    assert locked.json() == {"detail": "Too many failed login attempts. Try again later."}
    assert 0 < int(locked.headers["Retry-After"]) <= 15 * 60


def test_unknown_and_existing_usernames_behave_identically(limited, make_user):
    u = make_user("DOCTOR", username=f"real.{secrets.token_hex(3)}")
    ghost = f"ghost.{secrets.token_hex(3)}"
    responses = {name: [attempt(limited, name, "Wrong-Password-123") for _ in range(4)]
                 for name in (u["user"]["username"], ghost)}
    shapes = {name: [(r.status_code, r.json()["detail"]) for r in rs] for name, rs in responses.items()}
    assert shapes[u["user"]["username"]] == shapes[ghost]
    assert [s for s, _ in shapes[ghost]] == [401, 401, 401, 429]


def test_success_resets_the_username_counter(limited, make_user):
    u = make_user("DOCTOR", username=f"reset.{secrets.token_hex(3)}")
    for _ in range(2):
        attempt(limited, u["user"]["username"], u["password"] + "x")
    assert attempt(limited, u["user"]["username"], u["password"]).status_code == 200
    for _ in range(2):
        assert attempt(limited, u["user"]["username"], u["password"] + "x").status_code == 401
    assert attempt(limited, u["user"]["username"], u["password"]).status_code == 200


def test_per_ip_limit_across_many_usernames(limited, make_user):
    for i in range(6):
        assert attempt(limited, f"spray{i}.{secrets.token_hex(2)}", "Wrong-Password-123").status_code == 401
    u = make_user("DOCTOR", username=f"victim.{secrets.token_hex(3)}")
    assert attempt(limited, u["user"]["username"], u["password"]).status_code == 429  # this IP is throttled


def test_lockout_is_audited_and_expires(limited, make_user, test_engine, monkeypatch):
    from sqlalchemy import text

    import app.services.auth_service as auth_service

    u = make_user("DOCTOR", username=f"expire.{secrets.token_hex(3)}")
    for _ in range(3):
        attempt(limited, u["user"]["username"], u["password"] + "x")
    assert attempt(limited, u["user"]["username"], u["password"]).status_code == 429
    with test_engine.connect() as c:
        denied = c.execute(text("SELECT details FROM audit_events WHERE action = 'auth.login' AND outcome = 'DENIED' "
                                "AND actor_username = :u"), {"u": u["user"]["username"]}).scalars().all()
    assert denied == [{"reason": "locked", "limit_scope": "username", "failures": 3}]
    real_now = auth_service.utc_now
    monkeypatch.setattr(auth_service, "utc_now", lambda: real_now() + timedelta(minutes=16))
    assert attempt(limited, u["user"]["username"], u["password"]).status_code == 200
