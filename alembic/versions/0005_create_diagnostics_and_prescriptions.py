"""create diagnostics and prescriptions

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26 15:00:00.000000+00:00

Stage 3 — Diagnostics, Laboratory, Reports & Prescriptions. Creates:
- sequences lab_order_number_seq (LAB-000001), lab_sample_accession_seq (SMP-000001),
  prescription_number_seq (RX-000001), each OWNED BY its column;
- lab_orders, lab_samples, lab_results;
- reports;
- prescriptions, prescription_items.
No existing table changes.

Integrity enforced by PostgreSQL:
- every patient-scoped row references patients.id (ON DELETE RESTRICT);
- encounter links use the composite (encounter_id, patient_id) foreign key from Stage 2;
- samples, results and lab reports reference lab_orders through (lab_order_id, patient_id),
  so they can never point at another patient's order;
- lifecycle metadata (verified/released/cancelled/activated/completed) must match status;
- one result per analyte per order; unique human-facing numbers.

Reviewed against `alembic.autogenerate` output for the Stage 3 models; the sequences are
added by hand because autogenerate does not manage sequences.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEQUENCES = {
    # sequence name: (table, column)
    'lab_order_number_seq': ('lab_orders', 'order_number'),
    'lab_sample_accession_seq': ('lab_samples', 'accession_number'),
    'prescription_number_seq': ('prescriptions', 'prescription_number'),
}


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


def _same_patient_fk(table: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, 'patient_id'],
        [f'{target}.id', f'{target}.patient_id'],
        name=op.f(f'fk_{table}_{column}_{target}'),
        ondelete='RESTRICT',
    )


def upgrade() -> None:
    """Upgrade schema."""
    for name in SEQUENCES:
        op.execute(sa.schema.CreateSequence(sa.Sequence(name, start=1)))

    # --- laboratory -------------------------------------------------------------
    op.create_table(
        'lab_orders',
        *_record_columns(),
        sa.Column('order_number', sa.String(length=20), nullable=False),
        sa.Column('encounter_id', sa.Uuid(), nullable=False),
        sa.Column('test_code', sa.String(length=64), nullable=False),
        sa.Column('test_name', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('system_code', sa.String(length=64), nullable=True),
        sa.Column('priority', sa.String(length=10), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('clinical_indication', sa.String(length=500), nullable=True),
        sa.Column('ordered_by', sa.String(length=200), nullable=False),
        sa.Column('ordered_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('results_entered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by', sa.String(length=200), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)", name=op.f('ck_lab_orders_cancellation_matches_status')),
        sa.CheckConstraint("(status = 'RELEASED') = (released_at IS NOT NULL)", name=op.f('ck_lab_orders_release_matches_status')),
        sa.CheckConstraint("(verified_at IS NULL) = (verified_by IS NULL) AND ((status IN ('VERIFIED', 'RELEASED')) = (verified_at IS NOT NULL))", name=op.f('ck_lab_orders_verification_matches_status')),
        sa.CheckConstraint("order_number ~ '^LAB-[0-9]{6,}$'", name=op.f('ck_lab_orders_order_number_format')),
        sa.CheckConstraint("priority IN ('ROUTINE', 'URGENT', 'STAT')", name=op.f('ck_lab_orders_priority_valid')),
        sa.CheckConstraint("status IN ('ORDERED', 'SAMPLE_COLLECTED', 'PROCESSING', 'RESULT_ENTERED', 'VERIFIED', 'RELEASED', 'CANCELLED')", name=op.f('ck_lab_orders_status_valid')),
        sa.CheckConstraint("test_code ~ '^[a-z][a-z0-9_]*$'", name=op.f('ck_lab_orders_test_code_format')),
        sa.CheckConstraint('(code_system IS NULL) = (system_code IS NULL)', name=op.f('ck_lab_orders_coding_complete')),
        sa.CheckConstraint('(processing_started_at IS NULL OR processing_started_at >= ordered_at) AND (verified_at IS NULL OR verified_at >= ordered_at) AND (released_at IS NULL OR released_at >= verified_at)', name=op.f('ck_lab_orders_timestamps_ordered')),
        sa.CheckConstraint('length(btrim(ordered_by)) > 0', name=op.f('ck_lab_orders_ordered_by_not_blank')),
        sa.CheckConstraint('length(btrim(test_name)) > 0', name=op.f('ck_lab_orders_test_name_not_blank')),
        _same_patient_fk('lab_orders', 'encounter_id', 'encounters'),
        _patient_fk('lab_orders'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lab_orders')),
        sa.UniqueConstraint('id', 'patient_id', name='uq_lab_orders_id_patient_id'),
        sa.UniqueConstraint('order_number', name=op.f('uq_lab_orders_order_number')),
    )
    op.create_index('ix_lab_orders_encounter_id', 'lab_orders', ['encounter_id'], unique=False)
    op.create_index('ix_lab_orders_patient_id_ordered_at', 'lab_orders', ['patient_id', 'ordered_at'], unique=False)
    op.create_index('ix_lab_orders_status', 'lab_orders', ['status'], unique=False)

    op.create_table(
        'lab_samples',
        *_record_columns(),
        sa.Column('accession_number', sa.String(length=20), nullable=False),
        sa.Column('lab_order_id', sa.Uuid(), nullable=False),
        sa.Column('specimen_type', sa.String(length=20), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('collected_by', sa.String(length=200), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("accession_number ~ '^SMP-[0-9]{6,}$'", name=op.f('ck_lab_samples_accession_number_format')),
        sa.CheckConstraint("specimen_type IN ('BLOOD', 'SERUM', 'PLASMA', 'URINE', 'STOOL', 'SPUTUM', 'CSF', 'SWAB', 'TISSUE', 'OTHER')", name=op.f('ck_lab_samples_specimen_type_valid')),
        sa.CheckConstraint('length(btrim(collected_by)) > 0', name=op.f('ck_lab_samples_collected_by_not_blank')),
        _same_patient_fk('lab_samples', 'lab_order_id', 'lab_orders'),
        _patient_fk('lab_samples'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lab_samples')),
        sa.UniqueConstraint('accession_number', name=op.f('uq_lab_samples_accession_number')),
    )
    op.create_index('ix_lab_samples_lab_order_id', 'lab_samples', ['lab_order_id'], unique=False)
    op.create_index('ix_lab_samples_patient_id_collected_at', 'lab_samples', ['patient_id', 'collected_at'], unique=False)

    op.create_table(
        'lab_results',
        *_record_columns(),
        sa.Column('lab_order_id', sa.Uuid(), nullable=False),
        sa.Column('analyte_code', sa.String(length=64), nullable=False),
        sa.Column('analyte_name', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('system_code', sa.String(length=64), nullable=True),
        sa.Column('value_numeric', sa.Double(), nullable=True),
        sa.Column('value_text', sa.String(length=500), nullable=True),
        sa.Column('unit', sa.String(length=32), nullable=True),
        sa.Column('reference_low', sa.Double(), nullable=True),
        sa.Column('reference_high', sa.Double(), nullable=True),
        sa.Column('reference_text', sa.String(length=100), nullable=True),
        sa.Column('interpretation', sa.String(length=20), nullable=True),
        sa.Column('resulted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('entered_by', sa.String(length=200), nullable=False),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("analyte_code ~ '^[a-z][a-z0-9_]*$'", name=op.f('ck_lab_results_analyte_code_format')),
        sa.CheckConstraint("interpretation IS NULL OR interpretation IN ('NORMAL', 'LOW', 'HIGH', 'CRITICAL_LOW', 'CRITICAL_HIGH', 'ABNORMAL')", name=op.f('ck_lab_results_interpretation_valid')),
        sa.CheckConstraint('(code_system IS NULL) = (system_code IS NULL)', name=op.f('ck_lab_results_coding_complete')),
        sa.CheckConstraint('(reference_low IS NULL AND reference_high IS NULL) OR value_numeric IS NOT NULL', name=op.f('ck_lab_results_numeric_range_only_for_numeric')),
        sa.CheckConstraint('(value_numeric IS NULL) <> (value_text IS NULL)', name=op.f('ck_lab_results_exactly_one_value')),
        sa.CheckConstraint('length(btrim(analyte_name)) > 0', name=op.f('ck_lab_results_analyte_name_not_blank')),
        sa.CheckConstraint('length(btrim(entered_by)) > 0', name=op.f('ck_lab_results_entered_by_not_blank')),
        sa.CheckConstraint('reference_low IS NULL OR reference_high IS NULL OR reference_low <= reference_high', name=op.f('ck_lab_results_reference_range_ordered')),
        sa.CheckConstraint('value_text IS NULL OR unit IS NULL', name=op.f('ck_lab_results_unit_only_for_numeric')),
        _same_patient_fk('lab_results', 'lab_order_id', 'lab_orders'),
        _patient_fk('lab_results'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lab_results')),
        sa.UniqueConstraint('lab_order_id', 'analyte_code', name='uq_lab_results_lab_order_id_analyte_code'),
    )
    op.create_index('ix_lab_results_patient_id_resulted_at', 'lab_results', ['patient_id', 'resulted_at'], unique=False)

    # --- reports -----------------------------------------------------------------
    op.create_table(
        'reports',
        *_record_columns(),
        sa.Column('encounter_id', sa.Uuid(), nullable=True),
        sa.Column('lab_order_id', sa.Uuid(), nullable=True),
        sa.Column('report_type', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('code', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('requested_by', sa.String(length=200), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('author_name', sa.String(length=200), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('conclusion', sa.String(length=2000), nullable=True),
        sa.Column('verified_by', sa.String(length=200), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)", name=op.f('ck_reports_cancellation_matches_status')),
        sa.CheckConstraint("(status = 'RELEASED') = (released_at IS NOT NULL)", name=op.f('ck_reports_release_matches_status')),
        sa.CheckConstraint("(verified_at IS NULL) = (verified_by IS NULL) AND ((status IN ('VERIFIED', 'RELEASED')) = (verified_at IS NOT NULL) OR status = 'CANCELLED')", name=op.f('ck_reports_verification_matches_status')),
        sa.CheckConstraint("lab_order_id IS NULL OR report_type = 'LABORATORY'", name=op.f('ck_reports_lab_order_only_for_laboratory')),
        sa.CheckConstraint("report_type IN ('LABORATORY', 'IMAGING', 'CONSULTATION', 'DISCHARGE', 'PROCEDURE', 'OTHER')", name=op.f('ck_reports_report_type_valid')),
        sa.CheckConstraint("status IN ('DRAFT', 'CANCELLED') OR (content IS NOT NULL AND length(btrim(content)) > 0)", name=op.f('ck_reports_content_required_after_draft')),
        sa.CheckConstraint("status IN ('DRAFT', 'VERIFIED', 'RELEASED', 'CANCELLED')", name=op.f('ck_reports_status_valid')),
        sa.CheckConstraint('(code_system IS NULL) = (code IS NULL)', name=op.f('ck_reports_coding_complete')),
        sa.CheckConstraint('length(btrim(author_name)) > 0', name=op.f('ck_reports_author_name_not_blank')),
        sa.CheckConstraint('length(btrim(title)) > 0', name=op.f('ck_reports_title_not_blank')),
        sa.CheckConstraint('released_at IS NULL OR released_at >= verified_at', name=op.f('ck_reports_released_after_verified')),
        _same_patient_fk('reports', 'encounter_id', 'encounters'),
        _same_patient_fk('reports', 'lab_order_id', 'lab_orders'),
        _patient_fk('reports'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')),
    )
    op.create_index('ix_reports_encounter_id', 'reports', ['encounter_id'], unique=False)
    op.create_index('ix_reports_lab_order_id', 'reports', ['lab_order_id'], unique=False)
    op.create_index('ix_reports_patient_id_effective_at', 'reports', ['patient_id', 'effective_at'], unique=False)

    # --- prescriptions ---------------------------------------------------------------
    op.create_table(
        'prescriptions',
        *_record_columns(),
        sa.Column('prescription_number', sa.String(length=20), nullable=False),
        sa.Column('encounter_id', sa.Uuid(), nullable=False),
        sa.Column('prescriber_name', sa.String(length=200), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('prescribed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.String(length=2000), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)", name=op.f('ck_prescriptions_cancellation_matches_status')),
        sa.CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name=op.f('ck_prescriptions_completion_matches_status')),
        sa.CheckConstraint("(status = 'DRAFT') = (activated_at IS NULL) OR status = 'CANCELLED'", name=op.f('ck_prescriptions_activation_matches_status')),
        sa.CheckConstraint("prescription_number ~ '^RX-[0-9]{6,}$'", name=op.f('ck_prescriptions_prescription_number_format')),
        sa.CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'ON_HOLD', 'COMPLETED', 'CANCELLED')", name=op.f('ck_prescriptions_status_valid')),
        sa.CheckConstraint('(activated_at IS NULL OR activated_at >= prescribed_at) AND (completed_at IS NULL OR completed_at >= activated_at)', name=op.f('ck_prescriptions_timestamps_ordered')),
        sa.CheckConstraint('length(btrim(prescriber_name)) > 0', name=op.f('ck_prescriptions_prescriber_name_not_blank')),
        _same_patient_fk('prescriptions', 'encounter_id', 'encounters'),
        _patient_fk('prescriptions'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_prescriptions')),
        sa.UniqueConstraint('prescription_number', name=op.f('uq_prescriptions_prescription_number')),
    )
    op.create_index('ix_prescriptions_encounter_id', 'prescriptions', ['encounter_id'], unique=False)
    op.create_index('ix_prescriptions_patient_id_prescribed_at', 'prescriptions', ['patient_id', 'prescribed_at'], unique=False)
    op.create_index('ix_prescriptions_status', 'prescriptions', ['status'], unique=False)

    op.create_table(
        'prescription_items',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('prescription_id', sa.Uuid(), nullable=False),
        sa.Column('line_number', sa.Integer(), nullable=False),
        sa.Column('medicine_name', sa.String(length=255), nullable=False),
        sa.Column('code_system', sa.String(length=100), nullable=True),
        sa.Column('code', sa.String(length=64), nullable=True),
        sa.Column('dose_value', sa.Double(), nullable=False),
        sa.Column('dose_unit', sa.String(length=32), nullable=False),
        sa.Column('route', sa.String(length=20), nullable=False),
        sa.Column('frequency', sa.String(length=10), nullable=False),
        sa.Column('duration_value', sa.Integer(), nullable=True),
        sa.Column('duration_unit', sa.String(length=10), nullable=True),
        sa.Column('quantity', sa.Double(), nullable=True),
        sa.Column('quantity_unit', sa.String(length=32), nullable=True),
        sa.Column('instructions', sa.String(length=1000), nullable=True),
        *_system_timestamps(),
        sa.CheckConstraint("(duration_value IS NULL) = (duration_unit IS NULL) AND (duration_value IS NULL OR duration_value > 0) AND (duration_unit IS NULL OR duration_unit IN ('DAYS', 'WEEKS', 'MONTHS'))", name=op.f('ck_prescription_items_duration_valid')),
        sa.CheckConstraint("frequency IN ('ONCE', 'STAT', 'OD', 'BID', 'TID', 'QID', 'Q4H', 'Q6H', 'Q8H', 'Q12H', 'NOCTE', 'WEEKLY', 'PRN')", name=op.f('ck_prescription_items_frequency_valid')),
        sa.CheckConstraint("route IN ('ORAL', 'SUBLINGUAL', 'INTRAVENOUS', 'INTRAMUSCULAR', 'SUBCUTANEOUS', 'INHALED', 'TOPICAL', 'TRANSDERMAL', 'RECTAL', 'VAGINAL', 'OPHTHALMIC', 'OTIC', 'NASAL', 'OTHER')", name=op.f('ck_prescription_items_route_valid')),
        sa.CheckConstraint('(code_system IS NULL) = (code IS NULL)', name=op.f('ck_prescription_items_coding_complete')),
        sa.CheckConstraint('(quantity IS NULL OR quantity > 0) AND (quantity_unit IS NULL OR quantity IS NOT NULL)', name=op.f('ck_prescription_items_quantity_valid')),
        sa.CheckConstraint('dose_value > 0', name=op.f('ck_prescription_items_dose_positive')),
        sa.CheckConstraint('length(btrim(dose_unit)) > 0', name=op.f('ck_prescription_items_dose_unit_not_blank')),
        sa.CheckConstraint('length(btrim(medicine_name)) > 0', name=op.f('ck_prescription_items_medicine_name_not_blank')),
        sa.CheckConstraint('line_number >= 1', name=op.f('ck_prescription_items_line_number_positive')),
        sa.ForeignKeyConstraint(['prescription_id'], ['prescriptions.id'], name=op.f('fk_prescription_items_prescription_id_prescriptions'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_prescription_items')),
        sa.UniqueConstraint('prescription_id', 'line_number', name='uq_prescription_items_prescription_id_line_number'),
    )
    op.create_index('ix_prescription_items_prescription_id', 'prescription_items', ['prescription_id'], unique=False)

    for name, (table, column) in SEQUENCES.items():
        op.execute(f'ALTER SEQUENCE {name} OWNED BY {table}.{column}')


def downgrade() -> None:
    """Downgrade schema. Children first; indexes and OWNED BY sequences go with their tables."""
    op.drop_table('prescription_items')
    op.drop_table('prescriptions')
    op.drop_table('reports')
    op.drop_table('lab_results')
    op.drop_table('lab_samples')
    op.drop_table('lab_orders')
    for name in SEQUENCES:
        op.execute(f'DROP SEQUENCE IF EXISTS {name}')
