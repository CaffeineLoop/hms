"""create patients

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26 12:00:00.000000+00:00

Stage 1 — Patient Management. Creates:
- sequence `patient_number_seq` (source of PAT-000001 style Patient IDs; OWNED BY
  patients.patient_number so it is never shared with anything else)
- table `patients` (identity/demographics only; no clinical data) with its
  primary key, unique Patient ID, CHECK constraints and indexes.

Reviewed against `alembic.autogenerate` output for app.models.Patient; the
sequence is added by hand because autogenerate does not manage sequences.
Downgrade removes exactly these objects and nothing else.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(sa.schema.CreateSequence(sa.Sequence('patient_number_seq', start=1)))

    op.create_table(
        'patients',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('patient_number', sa.String(length=20), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('middle_name', sa.String(length=100), nullable=True),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=False),
        sa.Column('sex', sa.String(length=10), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('email', sa.String(length=254), nullable=True),
        sa.Column('address_line1', sa.String(length=200), nullable=True),
        sa.Column('address_line2', sa.String(length=200), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('state_province', sa.String(length=100), nullable=True),
        sa.Column('postal_code', sa.String(length=20), nullable=True),
        sa.Column('country', sa.String(length=100), nullable=True),
        sa.Column('emergency_contact_name', sa.String(length=200), nullable=True),
        sa.Column('emergency_contact_relationship', sa.String(length=50), nullable=True),
        sa.Column('emergency_contact_phone', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=10), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivation_reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "(status = 'ACTIVE' AND deactivated_at IS NULL AND deactivation_reason IS NULL)"
            " OR (status = 'INACTIVE' AND deactivated_at IS NOT NULL)",
            name=op.f('ck_patients_deactivation_consistent'),
        ),
        sa.CheckConstraint("date_of_birth >= DATE '1900-01-01'", name=op.f('ck_patients_date_of_birth_min')),
        sa.CheckConstraint("patient_number ~ '^PAT-[0-9]{6,}$'", name=op.f('ck_patients_patient_number_format')),
        sa.CheckConstraint("sex IN ('MALE', 'FEMALE', 'OTHER', 'UNKNOWN')", name=op.f('ck_patients_sex_valid')),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f('ck_patients_status_valid')),
        sa.CheckConstraint(
            '(emergency_contact_name IS NULL) = (emergency_contact_phone IS NULL)'
            ' AND (emergency_contact_relationship IS NULL OR emergency_contact_name IS NOT NULL)',
            name=op.f('ck_patients_emergency_contact_complete'),
        ),
        sa.CheckConstraint('length(btrim(first_name)) > 0', name=op.f('ck_patients_first_name_not_blank')),
        sa.CheckConstraint('length(btrim(last_name)) > 0', name=op.f('ck_patients_last_name_not_blank')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_patients')),
        sa.UniqueConstraint('patient_number', name=op.f('uq_patients_patient_number')),
    )
    op.execute('ALTER SEQUENCE patient_number_seq OWNED BY patients.patient_number')

    op.create_index(op.f('ix_patients_created_at'), 'patients', ['created_at'], unique=False)
    op.create_index(op.f('ix_patients_date_of_birth'), 'patients', ['date_of_birth'], unique=False)
    op.create_index(op.f('ix_patients_email'), 'patients', ['email'], unique=False)
    op.create_index(
        'ix_patients_lower_name_dob',
        'patients',
        [sa.literal_column('lower(last_name)'), sa.literal_column('lower(first_name)'), 'date_of_birth'],
        unique=False,
    )
    op.create_index(op.f('ix_patients_phone'), 'patients', ['phone'], unique=False)
    op.create_index(op.f('ix_patients_status'), 'patients', ['status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_patients_status'), table_name='patients')
    op.drop_index(op.f('ix_patients_phone'), table_name='patients')
    op.drop_index('ix_patients_lower_name_dob', table_name='patients')
    op.drop_index(op.f('ix_patients_email'), table_name='patients')
    op.drop_index(op.f('ix_patients_date_of_birth'), table_name='patients')
    op.drop_index(op.f('ix_patients_created_at'), table_name='patients')
    op.drop_table('patients')  # also drops the OWNED BY sequence
    op.execute('DROP SEQUENCE IF EXISTS patient_number_seq')
