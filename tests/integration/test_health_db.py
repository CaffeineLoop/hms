"""GET /health/db against the real test database, and when the database is down."""

import pytest
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from app.factory import create_app

pytestmark = pytest.mark.integration


def test_database_health_ok(client, alembic_config):
    response = client.get("/health/db")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "reachable"
    assert body["migration_revision"] == ScriptDirectory.from_config(alembic_config).get_current_head()
    assert body["latency_ms"] >= 0


def test_database_health_reports_503_when_unreachable(test_settings):
    unreachable = test_settings.model_copy(
        update={
            "database_url": type(test_settings.database_url)(
                "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_unreachable_test"
            ),
            "db_connect_timeout": 1,
        }
    )
    with TestClient(create_app(unreachable)) as client:
        response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "unreachable",
        "latency_ms": None,
        "migration_revision": None,
    }


def test_database_health_does_not_leak_connection_details(test_settings, client):
    url = test_settings.database_url_parsed
    text = client.get("/health/db").text
    for value in (url.password, url.username, url.host, url.database):
        if value:
            assert value not in text


def test_liveness_still_ok_when_database_unreachable(test_settings):
    unreachable = test_settings.model_copy(
        update={
            "database_url": type(test_settings.database_url)(
                "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_unreachable_test"
            ),
        }
    )
    with TestClient(create_app(unreachable)) as client:
        assert client.get("/health").status_code == 200
