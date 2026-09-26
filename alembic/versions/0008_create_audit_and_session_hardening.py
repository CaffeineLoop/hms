"""create audit trail and session hardening

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-26 19:00:00.000000+00:00

Stage 6 — Audit, Security & Hardening.

1. audit_events: append-only audit trail. No foreign keys (history must outlive and never
   block the records it describes). A trigger rejects UPDATE/DELETE (row level) and
   TRUNCATE (statement level) for every role that goes through normal SQL, so neither the
   application nor an ordinary database session can rewrite history.
2. permissions: `audit.view` is now in use; its seeded description is updated.
3. auth_sessions: `last_seen_at` (idle timeout) and `revocation_reason`. Sessions revoked
   before this migration get reason 'LEGACY' so the new consistency CHECK holds.

Generated with `alembic.autogenerate` for the table/columns; the trigger, the back-fill
and the CHECK on the existing table are added by hand (autogenerate handles none of them).
Destructive (downgrade) testing is done on hms_test only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REVOCATION_REASONS = (
    'LOGOUT', 'LOGOUT_ALL', 'PASSWORD_CHANGE', 'PASSWORD_RESET', 'USER_DEACTIVATED',
    'STAFF_DEACTIVATED', 'IDLE_TIMEOUT', 'LEGACY',
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=200), nullable=False),
        sa.Column('outcome', sa.String(length=10), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('actor_username', sa.String(length=100), nullable=True),
        sa.Column('actor_staff_id', sa.Uuid(), nullable=True),
        sa.Column('session_id', sa.Uuid(), nullable=True),
        sa.Column('resource_type', sa.String(length=50), nullable=True),
        sa.Column('resource_id', sa.String(length=100), nullable=True),
        sa.Column('patient_id', sa.Uuid(), nullable=True),
        sa.Column('http_method', sa.String(length=10), nullable=True),
        sa.Column('route', sa.String(length=200), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('client_ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f('ck_audit_events_details_is_object')),
        sa.CheckConstraint("outcome IN ('SUCCESS', 'FAILURE', 'DENIED')", name=op.f('ck_audit_events_outcome_valid')),
        sa.CheckConstraint('length(btrim(action)) > 0', name=op.f('ck_audit_events_action_not_blank')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events')),
    )
    op.create_index('ix_audit_events_actor_user_id_occurred_at', 'audit_events', ['actor_user_id', 'occurred_at'], unique=False)
    op.create_index('ix_audit_events_login_ip', 'audit_events', ['action', 'client_ip', 'occurred_at'], unique=False)
    op.create_index('ix_audit_events_login_username', 'audit_events', ['action', 'actor_username', 'occurred_at'], unique=False)
    op.create_index('ix_audit_events_occurred_at', 'audit_events', ['occurred_at'], unique=False)
    op.create_index('ix_audit_events_patient_id_occurred_at', 'audit_events', ['patient_id', 'occurred_at'], unique=False)
    op.create_index('ix_audit_events_resource', 'audit_events', ['resource_type', 'resource_id'], unique=False)

    op.execute("""
        CREATE FUNCTION audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER audit_events_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
    """)
    op.execute("""
        CREATE TRIGGER audit_events_no_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()
    """)

    op.execute("UPDATE permissions SET description = 'View the audit trail' WHERE code = 'audit.view'")

    op.add_column('auth_sessions', sa.Column('revocation_reason', sa.String(length=30), nullable=True))
    op.add_column('auth_sessions', sa.Column('last_seen_at', sa.DateTime(timezone=True),
                                             server_default=sa.text('now()'), nullable=False))
    op.execute("UPDATE auth_sessions SET revocation_reason = 'LEGACY' WHERE revoked_at IS NOT NULL")
    reasons = ", ".join(f"'{r}'" for r in REVOCATION_REASONS)
    op.create_check_constraint(
        op.f('ck_auth_sessions_revocation_matches_reason'),
        'auth_sessions',
        f"(revoked_at IS NULL) = (revocation_reason IS NULL) AND "
        f"(revocation_reason IS NULL OR revocation_reason IN ({reasons}))",
    )


def downgrade() -> None:
    """Downgrade schema. Dropping the table is allowed (the triggers only block row changes)."""
    op.drop_constraint(op.f('ck_auth_sessions_revocation_matches_reason'), 'auth_sessions', type_='check')
    op.drop_column('auth_sessions', 'last_seen_at')
    op.drop_column('auth_sessions', 'revocation_reason')
    op.execute("UPDATE permissions SET description = 'View audit trails (reserved for Stage 6)' WHERE code = 'audit.view'")
    op.drop_table('audit_events')  # drops its triggers too
    op.execute('DROP FUNCTION IF EXISTS audit_events_append_only()')
