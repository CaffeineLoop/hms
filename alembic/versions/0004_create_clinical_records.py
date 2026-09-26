"""create clinical records

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26 13:30:00.000000+00:00

Stage 2 — Clinical Records. Creates encounters, observations, conditions, allergies
and clinical_notes. Nothing in `patients` changes.

Integrity enforced by PostgreSQL:
- every record references patients.id (ON DELETE RESTRICT: patients are never deleted);
- records that reference an encounter do so through a composite foreign key
  (encounter_id, patient_id) -> encounters (id, patient_id), so a record can never be
  attached to another patient's encounter;
- controlled vocabularies, timestamp ordering and required-text rules are CHECK constraints;
- at most one ACTIVE allergy per patient and substance (partial unique index).

Reviewed against `alembic.autogenerate` output for the Stage 2 models (column order
rearranged for readability only).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _record_columns() -> list[sa.Column]:
    return [
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('patient_id', sa.Uuid(), nullable=False),
    ]


def _system_timestamps() -> list[sa.Column]:
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    ]


def _patient_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ['patient_id'], ['patients.id'], name=op.f(f'fk_{table}_patient_id_patients'), ondelete='RESTRICT'
    )


def _encounter_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ['encounter_id', 'patient_id'],
        ['encounters.id', 'encounters.patient_id'],
        name=op.f(f'fk_{table}_encounter_id_encounters'),
        ondelete='RESTRICT',
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'encounters',
        *_record_columns(),
        sa.Column('encounter_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.String(length=500), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("(status = 'CANCELLED') = (cancellation_reason IS NOT NULL)", name=op.f('ck_encounters_cancellation_reason_matches_status')),
        sa.CheckConstraint("(status = 'FINISHED') = (end_at IS NOT NULL) OR status = 'CANCELLED'", name=op.f('ck_encounters_end_matches_status')),
        sa.CheckConstraint("encounter_type IN ('OPD', 'EMERGENCY', 'INPATIENT', 'FOLLOW_UP')", name=op.f('ck_encounters_encounter_type_valid')),
        sa.CheckConstraint("status IN ('PLANNED', 'IN_PROGRESS', 'FINISHED', 'CANCELLED')", name=op.f('ck_encounters_status_valid')),
        sa.CheckConstraint('end_at IS NULL OR end_at >= start_at', name=op.f('ck_encounters_end_after_start')),
        sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_encounters_reason_not_blank')),
        _patient_fk('encounters'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_encounters')),
        sa.UniqueConstraint('id', 'patient_id', name='uq_encounters_id_patient_id'),
    )
    op.create_index('ix_encounters_patient_id_start_at', 'encounters', ['patient_id', 'start_at'], unique=False)
    op.create_index('ix_encounters_status', 'encounters', ['status'], unique=False)

    op.create_table(
        'observations',
        *_record_columns(),
        sa.Column('encounter_id', sa.Uuid(), nullable=True),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('display', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('system_code', sa.String(length=64), nullable=True),
        sa.Column('value_numeric', sa.Double(), nullable=True),
        sa.Column('value_text', sa.String(length=500), nullable=True),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name=op.f('ck_observations_code_format')),
        sa.CheckConstraint('(code_system IS NULL) = (system_code IS NULL)', name=op.f('ck_observations_coding_complete')),
        sa.CheckConstraint('(value_numeric IS NULL) <> (value_text IS NULL)', name=op.f('ck_observations_exactly_one_value')),
        sa.CheckConstraint('value_text IS NULL OR unit IS NULL', name=op.f('ck_observations_unit_only_for_numeric')),
        _encounter_fk('observations'),
        _patient_fk('observations'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_observations')),
    )
    op.create_index('ix_observations_encounter_id', 'observations', ['encounter_id'], unique=False)
    op.create_index('ix_observations_patient_id_code', 'observations', ['patient_id', 'code'], unique=False)
    op.create_index('ix_observations_patient_id_effective_at', 'observations', ['patient_id', 'effective_at'], unique=False)

    op.create_table(
        'conditions',
        *_record_columns(),
        sa.Column('encounter_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('code', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('onset_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("status IN ('SUSPECTED', 'ACTIVE', 'RESOLVED', 'HISTORICAL')", name=op.f('ck_conditions_status_valid')),
        sa.CheckConstraint('(code_system IS NULL) = (code IS NULL)', name=op.f('ck_conditions_coding_complete')),
        sa.CheckConstraint('length(btrim(name)) > 0', name=op.f('ck_conditions_name_not_blank')),
        sa.CheckConstraint('resolved_at IS NULL OR onset_at IS NULL OR resolved_at >= onset_at', name=op.f('ck_conditions_resolved_after_onset')),
        _encounter_fk('conditions'),
        _patient_fk('conditions'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_conditions')),
    )
    op.create_index('ix_conditions_encounter_id', 'conditions', ['encounter_id'], unique=False)
    op.create_index('ix_conditions_patient_id_recorded_at', 'conditions', ['patient_id', 'recorded_at'], unique=False)

    op.create_table(
        'allergies',
        *_record_columns(),
        sa.Column('encounter_id', sa.Uuid(), nullable=True),
        sa.Column('substance', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('code', sa.String(length=64), nullable=True),
        sa.Column('category', sa.String(length=20), nullable=True),
        sa.Column('reaction', sa.String(length=500), nullable=True),
        sa.Column('severity', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('onset_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("category IS NULL OR category IN ('FOOD', 'MEDICATION', 'ENVIRONMENT', 'BIOLOGIC')", name=op.f('ck_allergies_category_valid')),
        sa.CheckConstraint("severity IS NULL OR severity IN ('MILD', 'MODERATE', 'SEVERE')", name=op.f('ck_allergies_severity_valid')),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE', 'RESOLVED')", name=op.f('ck_allergies_status_valid')),
        sa.CheckConstraint('(code_system IS NULL) = (code IS NULL)', name=op.f('ck_allergies_coding_complete')),
        sa.CheckConstraint('length(btrim(substance)) > 0', name=op.f('ck_allergies_substance_not_blank')),
        _encounter_fk('allergies'),
        _patient_fk('allergies'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_allergies')),
    )
    op.create_index('ix_allergies_patient_id_recorded_at', 'allergies', ['patient_id', 'recorded_at'], unique=False)
    op.create_index(
        'uq_allergies_active_substance',
        'allergies',
        ['patient_id', sa.literal_column('lower(substance)')],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        'clinical_notes',
        *_record_columns(),
        sa.Column('encounter_id', sa.Uuid(), nullable=False),
        sa.Column('note_type', sa.String(length=30), nullable=False),
        sa.Column('author_name', sa.String(length=200), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('authored_at', sa.DateTime(timezone=True), nullable=False),
        *_system_timestamps(),
        sa.CheckConstraint("note_type IN ('PROGRESS', 'HISTORY_AND_PHYSICAL', 'CONSULTATION', 'NURSING', 'PROCEDURE', 'DISCHARGE_SUMMARY', 'OTHER')", name=op.f('ck_clinical_notes_note_type_valid')),
        sa.CheckConstraint('length(btrim(author_name)) > 0', name=op.f('ck_clinical_notes_author_name_not_blank')),
        sa.CheckConstraint('length(btrim(content)) > 0', name=op.f('ck_clinical_notes_content_not_blank')),
        _encounter_fk('clinical_notes'),
        _patient_fk('clinical_notes'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_clinical_notes')),
    )
    op.create_index('ix_clinical_notes_encounter_id', 'clinical_notes', ['encounter_id'], unique=False)
    op.create_index('ix_clinical_notes_patient_id_authored_at', 'clinical_notes', ['patient_id', 'authored_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema. Tables are dropped children-first; their indexes go with them."""
    op.drop_table('clinical_notes')
    op.drop_table('allergies')
    op.drop_table('conditions')
    op.drop_table('observations')
    op.drop_table('encounters')
