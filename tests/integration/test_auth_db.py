"""Stage 5 schema, seeds and constraints; migration 0007 on hms_test only."""

from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, pool, text
from sqlalchemy.exc import IntegrityError

from app.core.permissions import DEFAULT_ROLES, SUPER_ADMIN, P

pytestmark = pytest.mark.integration
AUTH = ("users", "roles", "permissions", "role_permissions", "user_roles", "auth_sessions")
HASH = "scrypt$14$8$5$c2FsdA==$a2V5"


def insert(connection, table, **values):
    cols, params = ", ".join(values), ", ".join(f":{k}" for k in values)
    return connection.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params}) RETURNING id"), values).scalar_one()


def violation(test_engine, statement) -> str:
    with pytest.raises(IntegrityError) as exc:
        with test_engine.begin() as connection:
            statement(connection)
    return exc.value.orig.diag.constraint_name


@pytest.fixture
def staff_id(test_engine, clean_patients):
    with test_engine.begin() as c:
        dept = insert(c, "departments", name="Admin", status="ACTIVE")
        return insert(c, "staff", employee_code="EMP-1", first_name="A", last_name="B", designation="ADMINISTRATOR",
                      department_id=dept, status="ACTIVE")


def user(staff_id, **overrides):
    return {"staff_id": staff_id, "username": "alice", "password_hash": HASH, "status": "ACTIVE",
            "password_changed_at": date(2026, 1, 1), **overrides}


def test_seeds_match_the_code_catalog(test_engine, clean_patients):
    with test_engine.connect() as c:
        codes = set(c.execute(text("SELECT code FROM permissions")).scalars())
        grants = c.execute(text(
            "SELECT r.name, p.code, rp.scope FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
            "JOIN permissions p ON p.id = rp.permission_id")).all()
        superusers = set(c.execute(text("SELECT name FROM roles WHERE is_superuser")).scalars())
    assert codes == {p.value for p in P}
    expected = {(r, c.value, s.value) for r, (_, g) in DEFAULT_ROLES.items() for c, s in g.items()}
    assert set(map(tuple, grants)) == expected
    assert superusers == {SUPER_ADMIN}


def test_user_constraints(test_engine, staff_id):
    assert violation(test_engine, lambda c: insert(c, "users", **user(staff_id, username="Bad Name"))) == "ck_users_username_format"
    assert violation(test_engine, lambda c: insert(c, "users", **user(staff_id, password_hash="plaintext"))
                     ) == "ck_users_password_hash_format"
    assert violation(test_engine, lambda c: insert(c, "users", **user(staff_id, status="INACTIVE"))
                     ) == "ck_users_deactivation_matches_status"
    with test_engine.begin() as c:
        insert(c, "users", **user(staff_id))
    assert violation(test_engine, lambda c: insert(c, "users", **user(staff_id, username="bob"))) == "uq_users_staff_id"


def test_role_and_grant_constraints(test_engine, clean_patients):
    assert violation(test_engine, lambda c: insert(c, "roles", name="lower", status="ACTIVE")) == "ck_roles_name_format"
    assert violation(test_engine, lambda c: insert(c, "roles", name="DOCTOR", status="ACTIVE")) == "uq_roles_name"
    with test_engine.begin() as c:
        role = insert(c, "roles", name="TEMP_ROLE", status="ACTIVE")
        perm = c.execute(text("SELECT id FROM permissions WHERE code = 'patient.view'")).scalar_one()
    assert violation(test_engine, lambda c: c.execute(text(
        "INSERT INTO role_permissions (role_id, permission_id, scope) VALUES (:r, :p, 'DEPARTMENT')"),
        {"r": role, "p": perm})) == "ck_role_permissions_scope_valid"
    assert violation(test_engine, lambda c: c.execute(text("DELETE FROM permissions WHERE id = :p"), {"p": perm})
                     ) == "fk_role_permissions_permission_id_permissions"


def test_session_constraints(test_engine, staff_id):
    with test_engine.begin() as c:
        uid = insert(c, "users", **user(staff_id))
    assert violation(test_engine, lambda c: c.execute(text(
        "INSERT INTO auth_sessions (user_id, token_hash, expires_at) VALUES (:u, 'not-a-digest', now() + interval '1 hour')"),
        {"u": uid})) == "ck_auth_sessions_token_hash_format"
    assert violation(test_engine, lambda c: c.execute(text(
        "INSERT INTO auth_sessions (user_id, token_hash, expires_at) VALUES (:u, :h, now() - interval '1 hour')"),
        {"u": uid, "h": "a" * 64})) == "ck_auth_sessions_expires_after_created"


def test_staff_with_account_cannot_be_deleted(test_engine, staff_id):
    with test_engine.begin() as c:
        insert(c, "users", **user(staff_id))
    assert violation(test_engine, lambda c: c.execute(text("DELETE FROM staff WHERE id = :s"), {"s": staff_id})
                     ) == "fk_users_staff_id_staff"


def test_migration_0007_downgrade_removes_only_auth_and_reseeds(test_database_url, alembic_config, staff_id):
    engine = create_engine(test_database_url, poolclass=pool.NullPool)
    try:
        command.downgrade(alembic_config, "0006")
        tables = set(inspect(engine).get_table_names())
        assert not tables & set(AUTH) and "staff" in tables
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM staff")).scalar_one() == 1  # Stage 4 data kept
        command.upgrade(alembic_config, "head")
        with engine.connect() as c:
            assert c.execute(text("SELECT count(*) FROM permissions")).scalar_one() == len(P)
            assert c.execute(text("SELECT count(*) FROM roles")).scalar_one() == len(DEFAULT_ROLES)
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
