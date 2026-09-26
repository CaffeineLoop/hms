"""Patient API behaviour that must hold without a working database.

Request validation happens before any database access, and a database outage
is reported as a clean 503 rather than a stack trace.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_principal
from app.core.config import load_settings
from app.factory import create_app
from tests.support import FULL_ACCESS

UNREACHABLE_DB_URL = "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_dev"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB_URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")
    app = create_app(load_settings(_env_file=None))
    app.dependency_overrides[get_principal] = lambda: FULL_ACCESS  # Stage 5: test past authentication
    with TestClient(app) as test_client:
        yield test_client


VALID = {"first_name": "Amina", "last_name": "Okafor", "date_of_birth": "1988-04-12", "sex": "FEMALE"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/patients/not-a-uuid"),
        ("get", "/api/patients/12345"),
        ("patch", "/api/patients/not-a-uuid"),
        ("post", "/api/patients/not-a-uuid/deactivate"),
        ("post", "/api/patients/not-a-uuid/reactivate"),
    ],
)
def test_invalid_uuid_is_422(client, method, path):
    kwargs = {"json": {"city": "Nairobi"}} if method == "patch" else {}
    if path.endswith("/deactivate"):
        kwargs = {"json": {"reason": "moved"}}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["path", "patient_id"]


def test_invalid_body_is_422_before_touching_database(client):
    response = client.post("/api/patients", json={**VALID, "date_of_birth": "2999-01-01"})
    assert response.status_code == 422
    assert "future" in response.json()["detail"][0]["msg"]


def test_malformed_json_is_422(client):
    response = client.post(
        "/api/patients", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_invalid_query_params_are_422(client):
    assert client.get("/api/patients", params={"limit": 0}).status_code == 422
    assert client.get("/api/patients", params={"limit": 1000}).status_code == 422
    assert client.get("/api/patients", params={"offset": -5}).status_code == 422
    assert client.get("/api/patients", params={"status": "DELETED"}).status_code == 422


def test_delete_is_not_allowed(client):
    assert client.delete(f"/api/patients/{uuid.uuid4()}").status_code == 405


def test_put_is_not_allowed(client):
    assert client.put(f"/api/patients/{uuid.uuid4()}", json=VALID).status_code == 405


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/patients", None),
        ("get", f"/api/patients/{uuid.uuid4()}", None),
        ("post", "/api/patients", VALID),
    ],
)
def test_database_unavailable_is_503_without_leaking_details(client, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body else {}))
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable. Please retry later."}
    for secret in ("127.0.0.1", "hms_app", "change-me", "hms_dev", "psycopg"):
        assert secret not in response.text
