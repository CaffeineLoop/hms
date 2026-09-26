"""Migration 0008 on hms_test only: upgrade/downgrade keep auth data; legacy revocations back-filled."""

from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, pool, text

pytestmark = pytest.mark.integration


def test_migration_0008_downgrade_upgrade_keeps_accounts(test_database_url, alembic_config, clean_patients):
    engine = create_engine(test_database_url, poolclass=pool.NullPool)
    try:
        with engine.begin() as c:
            dept = c.execute(text("INSERT INTO departments (name, status) VALUES ('Mig', 'ACTIVE') RETURNING id")).scalar_one()
            staff = c.execute(text(
                "INSERT INTO staff (employee_code, first_name, last_name, designation, department_id, status) "
                "VALUES ('MIG-1', 'M', 'G', 'OTHER', :d, 'ACTIVE') RETURNING id"), {"d": dept}).scalar_one()
            user = c.execute(text(
                "INSERT INTO users (staff_id, username, password_hash, status, password_changed_at) "
                "VALUES (:s, 'mig.user', 'scrypt$14$8$5$AA==$AA==', 'ACTIVE', :t) RETURNING id"),
                {"s": staff, "t": date(2026, 1, 1)}).scalar_one()
        command.downgrade(alembic_config, "0007")
        assert "audit_events" not in inspect(engine).get_table_names()
        assert {"last_seen_at", "revocation_reason"}.isdisjoint(c["name"] for c in inspect(engine).get_columns("auth_sessions"))
        with engine.begin() as c:  # a session revoked under Stage 5 (no reason column yet)
            c.execute(text("INSERT INTO auth_sessions (user_id, token_hash, expires_at, revoked_at) "
                           "VALUES (:u, :h, now() + interval '1 hour', now())"), {"u": user, "h": "b" * 64})
            description = c.execute(text("SELECT description FROM permissions WHERE code = 'audit.view'")).scalar_one()
        assert "reserved" in description
        command.upgrade(alembic_config, "head")
        with engine.connect() as c:
            assert c.execute(text("SELECT username FROM users WHERE id = :u"), {"u": user}).scalar_one() == "mig.user"
            assert c.execute(text("SELECT revocation_reason FROM auth_sessions WHERE token_hash = :h"),
                             {"h": "b" * 64}).scalar_one() == "LEGACY"
            assert c.execute(text("SELECT description FROM permissions WHERE code = 'audit.view'")).scalar_one() == \
                "View the audit trail"
            triggers = set(c.execute(text(
                "SELECT tgname FROM pg_trigger WHERE tgrelid = 'audit_events'::regclass AND NOT tgisinternal")).scalars())
        assert triggers == {"audit_events_no_update_delete", "audit_events_no_truncate"}
    finally:
        command.upgrade(alembic_config, "head")
        engine.dispose()
