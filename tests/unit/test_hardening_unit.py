"""Stage 6 unit tests: audit sanitizing/classification, authorship binding, error handling, headers."""

import logging
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_principal
from app.api.authorship import bind_actor
from app.api.middleware import _patient_id, _resource, _should_audit
from app.core.audit import sanitize
from app.core.config import load_settings
from app.core.errors import PermissionDeniedError
from app.core.principal import Principal
from app.factory import RedactQueryStringFilter, create_app
from app.schemas.clinical import ClinicalNoteCreate
from app.schemas.workflow import AdmissionApprove
from tests.support import FULL_ACCESS

DB = "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_dev"


@pytest.fixture
def offline_app(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")
    return create_app(load_settings(_env_file=None))


# --- audit metadata sanitizer ---------------------------------------------------------------------


def test_sanitize_drops_secret_keys_at_any_depth():
    secret = secrets.token_urlsafe(12)
    cleaned = sanitize({"password": secret, "new_password": secret, "access_token": secret, "Authorization": secret,
                        "api_key": secret, "role": "DOCTOR", "nested": {"token_hash": secret, "ok": 1}})
    assert cleaned == {"role": "DOCTOR", "nested": {"ok": 1}}
    assert secret not in repr(cleaned)


def test_sanitize_bounds_size_and_types():
    cleaned = sanitize({"long": "x" * 1000, "many": list(range(200)), "obj": uuid.UUID(int=1),
                        "deep": {"a": {"b": {"c": {"d": {"e": 1}}}}}})
    assert len(cleaned["long"]) == 200 and len(cleaned["many"]) == 50
    assert cleaned["obj"] == str(uuid.UUID(int=1))
    assert cleaned["deep"]["a"]["b"]["c"] == "[truncated]"


# --- middleware classification ---------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "route", "status", "expected"), [
    ("POST", "/api/patients", "/api/patients", 201, True),              # clinical mutation
    ("GET", "/api/patients/x", "/api/patients/{patient_id}", 200, True),  # sensitive read
    ("GET", "/api/staff", "/api/staff", 200, False),                   # non-patient read
    ("GET", "/api/staff", "/api/staff", 403, True),                    # denials always
    ("GET", "/api/anything", None, 401, True),
    ("GET", "/api/nope", None, 404, False),                            # unmatched noise
    ("POST", "/api/auth/login", "/api/auth/login", 401, False),        # audited by AuthService
    ("POST", "/api/roles", "/api/roles", 201, False),                  # explicit service event
    ("POST", "/api/roles", "/api/roles", 409, True),                   # ...but failures are recorded
    ("GET", "/api/audit-events", "/api/audit-events", 200, True),      # reading the audit trail
    ("GET", "/health", "/health", 200, False),
])
def test_should_audit(method, path, route, status, expected):
    assert _should_audit(method, path, route, status) is expected


def test_resource_inference():
    pid = str(uuid.uuid4())
    assert _resource("/api/patients/{patient_id}/clinical-notes", {"patient_id": pid},
                     f"/api/clinical-notes/{uuid.UUID(int=5)}") == ("clinical-notes", str(uuid.UUID(int=5)))
    assert _resource("/api/encounters/{encounter_id}/finish", {"encounter_id": "e1"}, None) == ("encounters", "e1")
    assert _resource("/api/patients", {}, None) == ("patients", None)
    assert _resource("/api/roles/{role_id}/permissions/{code}", {"role_id": "r", "code": "patient.view"}, None) == \
        ("permissions", "patient.view")
    assert _patient_id({"patient_id": pid}, "clinical-notes", None) == uuid.UUID(pid)
    assert _patient_id({}, "patients", pid) == uuid.UUID(pid)
    assert _patient_id({"patient_id": "not-a-uuid"}, None, None) is None


def test_access_log_query_strings_are_redacted():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", "/api/patients?q=Jane%20Doe", "1.1", 200), None)
    RedactQueryStringFilter().filter(record)
    assert "Jane" not in record.getMessage() and "/api/patients" in record.getMessage()


# --- authorship binding -----------------------------------------------------------------------------


def note(**kw):
    return ClinicalNoteCreate(encounter_id=uuid.uuid4(), note_type="PROGRESS", content="x", **kw)


def test_bind_actor_uses_the_callers_staff():
    me = uuid.uuid4()
    caller = Principal(user_id=uuid.uuid4(), staff_id=me, username="dr")
    assert bind_actor(note(), caller, "author_staff_id", "author_name").author_staff_id == me
    assert bind_actor(note(author_staff_id=me), caller, "author_staff_id", "author_name").author_staff_id == me
    assert bind_actor(AdmissionApprove(), caller, "approved_by_staff_id").approved_by_staff_id == me


def test_bind_actor_rejects_impersonation_and_free_text():
    caller = Principal(user_id=uuid.uuid4(), staff_id=uuid.uuid4(), username="dr")
    with pytest.raises(PermissionDeniedError, match="on behalf of another staff member"):
        bind_actor(note(author_staff_id=uuid.uuid4()), caller, "author_staff_id", "author_name")
    with pytest.raises(PermissionDeniedError, match="author_name cannot be supplied"):
        bind_actor(note(author_name="Dr. Someone Else"), caller, "author_staff_id", "author_name")
    with pytest.raises(PermissionDeniedError):
        bind_actor(AdmissionApprove(approved_by_staff_id=uuid.uuid4()), caller, "approved_by_staff_id")


def test_bind_actor_keeps_explicit_identity_for_principals_without_staff():
    data = note(author_name="Dr. Visiting Consultant")
    assert bind_actor(data, FULL_ACCESS, "author_staff_id", "author_name") is data


# --- error handling / headers ------------------------------------------------------------------------


def test_validation_errors_do_not_echo_input(offline_app):
    secret = secrets.token_urlsafe(16)
    with TestClient(offline_app) as client:
        response = client.post("/api/auth/login", json={"username": ["not", "a", "string"], "password": secret,
                                                        "unexpected": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert all(set(error) == {"type", "loc", "msg"} for error in response.json()["detail"])  # no input/ctx
    assert {tuple(e["loc"]) for e in response.json()["detail"]} >= {("body", "username"), ("body", "unexpected")}


def test_unhandled_errors_are_generic_and_do_not_log_messages(offline_app, caplog):
    marker = "Patient Jane Doe DOB 1970-01-01"

    @offline_app.get("/api/boom-test-only")
    def boom():
        raise RuntimeError(marker)

    offline_app.dependency_overrides[get_principal] = lambda: FULL_ACCESS
    with caplog.at_level(logging.ERROR), TestClient(offline_app, raise_server_exceptions=False) as client:
        response = client.get("/api/boom-test-only")
    assert response.status_code == 500 and response.json() == {"detail": "Internal server error."}
    assert marker not in response.text and "Traceback" not in response.text
    assert "RuntimeError" in caplog.text and marker not in caplog.text


def test_security_headers_and_request_id(offline_app):
    with TestClient(offline_app) as client:
        response = client.get("/health")
        api = client.get("/api/patients")  # 401, still hardened
        echoed = client.get("/health", headers={"X-Request-ID": "abc-123"})
        rejected = client.get("/health", headers={"X-Request-ID": "<script>" * 20})
    for r in (response, api):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY" and r.headers["Referrer-Policy"] == "no-referrer"
        assert len(r.headers["X-Request-ID"]) >= 6
    assert api.headers["Cache-Control"] == "no-store"
    assert echoed.headers["X-Request-ID"] == "abc-123"
    assert "<script>" not in rejected.headers["X-Request-ID"]


def test_production_disables_interactive_docs(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", DB)
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(create_app(load_settings(_env_file=None))) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200
