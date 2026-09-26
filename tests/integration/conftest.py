"""Fixtures for tests that write patient data to the isolated test database."""

from collections.abc import Callable

import pytest
from sqlalchemy import Engine, text

from app.core.permissions import DEFAULT_ROLES, SUPER_ADMIN
from app.db.session import build_session_factory


# Children before parents: every clinical table references patients with ON DELETE RESTRICT.
CLINICAL_TABLES = (
    "workflow_tasks", "admission_transfers", "admissions", "appointments",
    "prescription_items", "prescriptions", "reports", "lab_results", "lab_samples", "lab_orders",
    "clinical_notes", "allergies", "conditions", "observations", "encounters",
)
# Staff tables are referenced by clinical rows, so they are cleared after them.
STAFF_TABLES = ("staff", "departments")
# Auth rows reference staff; they go first. Roles/grants are reset to the seeded defaults.
AUTH_TABLES = ("auth_sessions", "user_roles", "users")


def reset_roles_to_defaults(connection) -> None:
    connection.execute(text("DELETE FROM role_permissions"))
    connection.execute(text("DELETE FROM roles WHERE name <> ALL(:names)"), {"names": list(DEFAULT_ROLES)})
    connection.execute(
        text("UPDATE roles SET status = 'ACTIVE', description = :d, is_superuser = :su WHERE name = :n"),
        [{"d": d, "su": n == SUPER_ADMIN, "n": n} for n, (d, _) in DEFAULT_ROLES.items()],
    )
    grants = [(n, c.value, s.value) for n, (_, g) in DEFAULT_ROLES.items() for c, s in g.items()]
    connection.execute(text(
        "INSERT INTO role_permissions (role_id, permission_id, scope) "
        "SELECT r.id, p.id, g.scope FROM unnest(CAST(:roles AS text[]), CAST(:codes AS text[]), CAST(:scopes AS text[]))"
        " AS g(role, code, scope) JOIN roles r ON r.name = g.role JOIN permissions p ON p.code = g.code"
    ), {"roles": [g[0] for g in grants], "codes": [g[1] for g in grants], "scopes": [g[2] for g in grants]})


@pytest.fixture
def clean_patients(test_engine: Engine) -> None:
    """Start every test from empty domain tables and default roles (test database only)."""
    with test_engine.begin() as connection:
        # Grants may reference the users who made them, so they are cleared first.
        connection.execute(text("DELETE FROM role_permissions"))
        for table in (*AUTH_TABLES, *CLINICAL_TABLES, "patients", *STAFF_TABLES):
            connection.execute(text(f"DELETE FROM {table}"))
        reset_roles_to_defaults(connection)


@pytest.fixture
def db_session(test_engine: Engine, clean_patients: None):
    with build_session_factory(test_engine)() as session:
        yield session


@pytest.fixture
def patient_payload() -> Callable[..., dict]:
    def build(**overrides) -> dict:
        data = {
            "first_name": "Amina",
            "last_name": "Okafor",
            "date_of_birth": "1988-04-12",
            "sex": "FEMALE",
        }
        data.update(overrides)
        return data

    return build


@pytest.fixture
def make_department(client) -> Callable[..., dict]:
    counter = iter(range(1, 10_000))

    def build(**overrides) -> dict:
        body = {"name": f"Department {next(counter)}", "description": "Test department", **overrides}
        response = client.post("/api/departments", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return build


@pytest.fixture
def make_staff(client, make_department) -> Callable[..., dict]:
    counter = iter(range(1, 10_000))

    def build(department: dict | None = None, **overrides) -> dict:
        department = department or make_department()
        n = next(counter)
        body = {"employee_code": f"EMP-{n:04d}", "first_name": f"Staff{n}", "last_name": "Member",
                "designation": "DOCTOR", "department_id": department["id"], **overrides}
        response = client.post("/api/staff", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    return build


def strong_password() -> str:
    """Generated per test: no password literals in the repository (see test_no_hardcoded_secrets)."""
    import secrets

    return "Hx9-" + secrets.token_urlsafe(18)


@pytest.fixture
def make_user(client, auth_client, make_staff) -> Callable[..., dict]:
    """Create a real user holding the named roles (created by the full-access client) and log in.

    Returns {"user", "staff", "password", "token", "headers"}.
    """

    def build(*roles: str, staff: dict | None = None, username: str | None = None, **staff_overrides) -> dict:
        staff = staff or make_staff(**staff_overrides)
        role_ids = [r["id"] for r in client.get("/api/roles", params={"limit": 100}).json()["items"]
                    if r["name"] in roles]
        assert len(role_ids) == len(roles), f"unknown role in {roles}"
        password = strong_password()
        response = client.post("/api/users", json={
            "staff_id": staff["id"], "username": username or staff["employee_code"].lower(),
            "password": password, "role_ids": role_ids})
        assert response.status_code == 201, response.text
        user = response.json()
        login = auth_client.post("/api/auth/login", json={"username": user["username"], "password": password})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
        return {"user": user, "staff": staff, "password": password, "token": token,
                "headers": {"Authorization": f"Bearer {token}"}}

    return build
