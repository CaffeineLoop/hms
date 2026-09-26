"""Application imports/starts, and the liveness endpoint works without a database."""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.config import ConfigurationError, load_settings
from app.factory import create_app

# Points at a port nothing listens on. Liveness must not need it.
UNUSED_DB_URL = "postgresql+psycopg://hms_app:change-me@127.0.0.1:1/hms_dev"


@pytest.fixture
def offline_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNUSED_DB_URL)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DB_CONNECT_TIMEOUT", "1")
    return load_settings(_env_file=None)


@pytest.fixture
def fresh_main_import(monkeypatch):
    """Re-import app.main with a clean settings cache, then restore state afterwards."""
    config.get_settings.cache_clear()
    sys.modules.pop("app.main", None)
    yield
    config.get_settings.cache_clear()
    sys.modules.pop("app.main", None)


def test_entry_module_imports_and_builds_app(monkeypatch, fresh_main_import):
    monkeypatch.setenv("DATABASE_URL", UNUSED_DB_URL)
    main = importlib.import_module("app.main")
    paths = set(main.app.openapi()["paths"])
    assert {"/health", "/health/db"} <= paths


def test_entry_module_fails_clearly_without_database_url(monkeypatch, fresh_main_import):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Also stop pydantic-settings from reading the developer's .env for this import.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        importlib.import_module("app.main")


def test_app_starts_and_shuts_down(offline_settings):
    app = create_app(offline_settings)
    with TestClient(app):  # runs lifespan startup and shutdown
        assert app.state.settings is offline_settings
        assert app.state.session_factory is not None


def test_health_returns_expected_response(offline_settings):
    with TestClient(create_app(offline_settings)) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "Hospital Management System",
        "environment": "test",
    }


def test_health_rejects_wrong_method(offline_settings):
    with TestClient(create_app(offline_settings)) as client:
        assert client.post("/health").status_code == 405


def test_unknown_route_is_404(offline_settings):
    with TestClient(create_app(offline_settings)) as client:
        assert client.get("/patients").status_code == 404


def test_openapi_schema_lists_only_expected_endpoints(offline_settings):
    with TestClient(create_app(offline_settings)) as client:
        schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/health",
        "/health/db",
        "/api/patients",
        "/api/patients/{patient_id}",
        "/api/patients/{patient_id}/deactivate",
        "/api/patients/{patient_id}/reactivate",
        "/api/patients/{patient_id}/encounters",
        "/api/patients/{patient_id}/observations",
        "/api/patients/{patient_id}/conditions",
        "/api/patients/{patient_id}/allergies",
        "/api/patients/{patient_id}/clinical-notes",
        "/api/patients/{patient_id}/timeline",
        "/api/encounters/{encounter_id}",
        "/api/encounters/{encounter_id}/start",
        "/api/encounters/{encounter_id}/finish",
        "/api/encounters/{encounter_id}/cancel",
        "/api/observations/{observation_id}",
        "/api/conditions/{condition_id}",
        "/api/allergies/{allergy_id}",
        "/api/clinical-notes/{note_id}",
        "/api/patients/{patient_id}/lab-orders",
        "/api/lab-orders/{order_id}",
        "/api/lab-orders/{order_id}/samples",
        "/api/lab-orders/{order_id}/start-processing",
        "/api/lab-orders/{order_id}/results",
        "/api/lab-orders/{order_id}/verify",
        "/api/lab-orders/{order_id}/release",
        "/api/lab-orders/{order_id}/cancel",
        "/api/lab-samples/{sample_id}",
        "/api/lab-results/{result_id}",
        "/api/patients/{patient_id}/reports",
        "/api/reports/{report_id}",
        "/api/reports/{report_id}/verify",
        "/api/reports/{report_id}/release",
        "/api/reports/{report_id}/cancel",
        "/api/patients/{patient_id}/prescriptions",
        "/api/prescriptions/{prescription_id}",
        "/api/prescriptions/{prescription_id}/items",
        "/api/prescriptions/{prescription_id}/activate",
        "/api/prescriptions/{prescription_id}/hold",
        "/api/prescriptions/{prescription_id}/resume",
        "/api/prescriptions/{prescription_id}/complete",
        "/api/prescriptions/{prescription_id}/cancel",
        "/api/departments",
        "/api/departments/{department_id}",
        "/api/departments/{department_id}/deactivate",
        "/api/departments/{department_id}/reactivate",
        "/api/staff",
        "/api/staff/{staff_id}",
        "/api/staff/{staff_id}/deactivate",
        "/api/staff/{staff_id}/reactivate",
        "/api/patients/{patient_id}/appointments",
        "/api/appointments",
        "/api/appointments/{appointment_id}",
        "/api/appointments/{appointment_id}/confirm",
        "/api/appointments/{appointment_id}/check-in",
        "/api/appointments/{appointment_id}/start-consultation",
        "/api/appointments/{appointment_id}/complete",
        "/api/appointments/{appointment_id}/no-show",
        "/api/appointments/{appointment_id}/cancel",
        "/api/patients/{patient_id}/admissions",
        "/api/admissions",
        "/api/admissions/{admission_id}",
        "/api/admissions/{admission_id}/approve",
        "/api/admissions/{admission_id}/admit",
        "/api/admissions/{admission_id}/transfer",
        "/api/admissions/{admission_id}/discharge",
        "/api/admissions/{admission_id}/cancel",
        "/api/workflow-tasks",
        "/api/workflow-tasks/{task_id}",
        "/api/workflow-tasks/{task_id}/assign",
        "/api/workflow-tasks/{task_id}/start",
        "/api/workflow-tasks/{task_id}/complete",
        "/api/workflow-tasks/{task_id}/cancel",
        "/api/auth/login",
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/logout-all",
        "/api/auth/change-password",
        "/api/users",
        "/api/users/{user_id}",
        "/api/users/{user_id}/deactivate",
        "/api/users/{user_id}/reactivate",
        "/api/users/{user_id}/reset-password",
        "/api/users/{user_id}/roles",
        "/api/users/{user_id}/roles/{role_id}",
        "/api/roles",
        "/api/roles/{role_id}",
        "/api/roles/{role_id}/deactivate",
        "/api/roles/{role_id}/reactivate",
        "/api/roles/{role_id}/permissions",
        "/api/roles/{role_id}/permissions/{code}",
        "/api/permissions",
        "/api/audit-events",
        "/api/audit-events/{event_id}",
        "/api/ai/capabilities",
        "/api/ai/analyses",
    }
