"""ai risk analysis review pathway

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27 12:00:00.000000+00:00

Stage 8 — Four-Day Clinical Risk Analysis.

1. ai_risk_analyses: stored four-day potential-risk analyses awaiting human review. Separate from
   every clinical table (nothing clinical references it). CHECK constraints fix the horizon at
   exactly 4 days from the reference time and require human review.
2. A trigger makes the analysis content immutable: an UPDATE may only record the (single) review
   of a PENDING_REVIEW analysis; every other column is frozen.
3. permissions: `ai.review` (seeded in 0007 as reserved) is now enforced; its description is
   updated. No role grants (administrators decide who reviews AI output).
Destructive (downgrade) testing is done on hms_test only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

REVIEW_COLUMNS = ("review_status", "reviewed_by_user_id", "reviewed_by_staff_id", "reviewed_at", "review_comment")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'ai_risk_analyses',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('patient_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('reason_code', sa.String(length=50), nullable=True),
        sa.Column('trigger', sa.String(length=10), nullable=False),
        sa.Column('trigger_event', sa.String(length=50), nullable=True),
        sa.Column('trigger_source_id', sa.Uuid(), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('requested_by_user_id', sa.Uuid(), nullable=False),
        sa.Column('requested_by_staff_id', sa.Uuid(), nullable=False),
        sa.Column('reference_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('horizon_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('horizon_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('analysis_horizon_days', sa.SmallInteger(), server_default=sa.text('4'), nullable=False),
        sa.Column('ruleset_id', sa.String(length=50), nullable=False),
        sa.Column('ruleset_version', sa.String(length=20), nullable=False),
        sa.Column('ruleset_validated', sa.Boolean(), nullable=False),
        sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('data_gaps', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('max_priority', sa.String(length=10), nullable=True),
        sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('provider', sa.String(length=20), nullable=False),
        sa.Column('model', sa.String(length=100), nullable=False),
        sa.Column('requires_human_review', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('review_status', sa.String(length=20), server_default=sa.text("'PENDING_REVIEW'"), nullable=False),
        sa.Column('reviewed_by_user_id', sa.Uuid(), nullable=True),
        sa.Column('reviewed_by_staff_id', sa.Uuid(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_comment', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('COMPLETED', 'ABSTAINED')", name=op.f('ck_ai_risk_analyses_status_valid')),
        sa.CheckConstraint("trigger IN ('MANUAL', 'EVENT')", name=op.f('ck_ai_risk_analyses_trigger_valid')),
        sa.CheckConstraint("(trigger = 'EVENT') = (trigger_event IS NOT NULL)",
                           name=op.f('ck_ai_risk_analyses_trigger_event_matches')),
        sa.CheckConstraint('analysis_horizon_days = 4', name=op.f('ck_ai_risk_analyses_horizon_is_four_days')),
        sa.CheckConstraint('horizon_start = reference_at', name=op.f('ck_ai_risk_analyses_horizon_starts_at_reference')),
        sa.CheckConstraint("horizon_end = horizon_start + interval '4 days'",
                           name=op.f('ck_ai_risk_analyses_horizon_end_matches')),
        sa.CheckConstraint("jsonb_typeof(signals) = 'array'", name=op.f('ck_ai_risk_analyses_signals_is_array')),
        sa.CheckConstraint("jsonb_typeof(data_gaps) = 'array'", name=op.f('ck_ai_risk_analyses_data_gaps_is_array')),
        sa.CheckConstraint("output IS NULL OR jsonb_typeof(output) = 'object'",
                           name=op.f('ck_ai_risk_analyses_output_is_object')),
        sa.CheckConstraint("max_priority IS NULL OR max_priority IN ('LOW', 'MODERATE', 'HIGH')",
                           name=op.f('ck_ai_risk_analyses_max_priority_valid')),
        sa.CheckConstraint('requires_human_review', name=op.f('ck_ai_risk_analyses_requires_human_review')),
        sa.CheckConstraint("review_status IN ('PENDING_REVIEW', 'ACKNOWLEDGED', 'DISMISSED')",
                           name=op.f('ck_ai_risk_analyses_review_status_valid')),
        sa.CheckConstraint(
            "(review_status = 'PENDING_REVIEW') = (reviewed_at IS NULL) "
            "AND (reviewed_at IS NULL) = (reviewed_by_user_id IS NULL) "
            "AND (reviewed_at IS NULL) = (reviewed_by_staff_id IS NULL) "
            "AND (review_comment IS NULL OR reviewed_at IS NOT NULL)",
            name=op.f('ck_ai_risk_analyses_review_consistent')),
        sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_ai_risk_analyses_patient_id_patients'),
                                ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['requested_by_staff_id'], ['staff.id'],
                                name=op.f('fk_ai_risk_analyses_requested_by_staff_id_staff'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['requested_by_user_id'], ['users.id'],
                                name=op.f('fk_ai_risk_analyses_requested_by_user_id_users'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewed_by_staff_id'], ['staff.id'],
                                name=op.f('fk_ai_risk_analyses_reviewed_by_staff_id_staff'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'],
                                name=op.f('fk_ai_risk_analyses_reviewed_by_user_id_users'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_risk_analyses')),
    )
    op.create_index('ix_ai_risk_analyses_patient_id_created_at', 'ai_risk_analyses', ['patient_id', 'created_at'])
    op.create_index('ix_ai_risk_analyses_review_status_created_at', 'ai_risk_analyses', ['review_status', 'created_at'])
    op.create_index('ix_ai_risk_analyses_patient_trigger_created_at', 'ai_risk_analyses',
                    ['patient_id', 'trigger', 'created_at'])

    frozen = " - ".join(f"'{c}'" for c in REVIEW_COLUMNS)
    op.execute(f"""
        CREATE FUNCTION ai_risk_analyses_review_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.review_status <> 'PENDING_REVIEW' THEN
                RAISE EXCEPTION 'ai_risk_analyses: this analysis has already been reviewed'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF (to_jsonb(NEW) - {frozen}) IS DISTINCT FROM (to_jsonb(OLD) - {frozen}) THEN
                RAISE EXCEPTION 'ai_risk_analyses: analysis content is immutable (only the review may be recorded)'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER ai_risk_analyses_review_only
        BEFORE UPDATE ON ai_risk_analyses
        FOR EACH ROW EXECUTE FUNCTION ai_risk_analyses_review_only()
    """)

    op.execute("UPDATE permissions SET description = 'Review AI risk analyses (acknowledge or dismiss)' "
               "WHERE code = 'ai.review'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE permissions SET description = 'Review AI output (reserved for a later stage)' "
               "WHERE code = 'ai.review'")
    op.drop_table('ai_risk_analyses')  # drops its trigger and indexes too
    op.execute('DROP FUNCTION IF EXISTS ai_risk_analyses_review_only()')
