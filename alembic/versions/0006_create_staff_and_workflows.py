"""create staff and hospital workflows

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26 16:00:00.000000+00:00

Stage 4 — Staff & Hospital Workflows.

New tables: departments, staff, appointments, admissions, admission_transfers,
workflow_tasks.

Staff references on earlier clinical records (additive, all NULLABLE, no data change):
    encounters.attending_staff_id
    clinical_notes.author_staff_id
    lab_orders.ordered_by_staff_id, lab_orders.verified_by_staff_id
    lab_samples.collected_by_staff_id
    lab_results.entered_by_staff_id
    reports.author_staff_id, reports.requested_by_staff_id, reports.verified_by_staff_id
    prescriptions.prescriber_staff_id
The existing free-text name columns are kept: they hold a name snapshot for new records
and the original free text for records created before Stage 4 (and for imported data
whose practitioners are not HMS staff). Existing rows are untouched; nothing is
back-filled, because free-text names cannot be matched to staff reliably.

All staff/department foreign keys are ON DELETE RESTRICT. Integrity rules:
- one open admission per patient (partial unique index);
- appointment/admission encounters must belong to the same patient (composite FKs);
- lifecycle metadata must agree with status (CHECK constraints).

Generated with `alembic.autogenerate` against the Stage 4 models and reviewed; the
downgrade is written by hand (drop added columns first, then tables child-first).
Destructive (downgrade) testing is done on hms_test only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STAFF_REFERENCES = [
    ('encounters', 'attending_staff_id'),
    ('clinical_notes', 'author_staff_id'),
    ('lab_orders', 'ordered_by_staff_id'),
    ('lab_orders', 'verified_by_staff_id'),
    ('lab_samples', 'collected_by_staff_id'),
    ('lab_results', 'entered_by_staff_id'),
    ('reports', 'author_staff_id'),
    ('reports', 'requested_by_staff_id'),
    ('reports', 'verified_by_staff_id'),
    ('prescriptions', 'prescriber_staff_id'),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('departments',
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f('ck_departments_status_valid')),
    sa.CheckConstraint('length(btrim(name)) > 0', name=op.f('ck_departments_name_not_blank')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_departments'))
    )
    op.create_index('uq_departments_lower_name', 'departments', [sa.literal_column('lower(name)')], unique=True)
    op.create_table('staff',
    sa.Column('employee_code', sa.String(length=20), nullable=False),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('designation', sa.String(length=20), nullable=False),
    sa.Column('department_id', sa.Uuid(), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'INACTIVE') = (deactivated_at IS NOT NULL)", name=op.f('ck_staff_deactivation_matches_status')),
    sa.CheckConstraint("designation IN ('DOCTOR', 'CLINICAL_OFFICER', 'NURSE', 'MIDWIFE', 'LAB_TECHNICIAN', 'PHARMACIST', 'RADIOGRAPHER', 'RECEPTIONIST', 'ADMINISTRATOR', 'OTHER')", name=op.f('ck_staff_designation_valid')),
    sa.CheckConstraint("employee_code ~ '^[A-Z0-9][A-Z0-9-]{1,19}$'", name=op.f('ck_staff_employee_code_format')),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f('ck_staff_status_valid')),
    sa.CheckConstraint('length(btrim(first_name)) > 0', name=op.f('ck_staff_first_name_not_blank')),
    sa.CheckConstraint('length(btrim(last_name)) > 0', name=op.f('ck_staff_last_name_not_blank')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_staff_department_id_departments'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_staff')),
    sa.UniqueConstraint('employee_code', name=op.f('uq_staff_employee_code'))
    )
    op.create_index('ix_staff_department_id', 'staff', ['department_id'], unique=False)
    op.create_index('ix_staff_lower_name', 'staff', [sa.literal_column('lower(last_name)'), sa.literal_column('lower(first_name)')], unique=False)
    op.create_index('uq_staff_lower_email', 'staff', [sa.literal_column('lower(email)')], unique=True, postgresql_where=sa.text('email IS NOT NULL'))
    op.create_table('workflow_tasks',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=True),
    sa.Column('department_id', sa.Uuid(), nullable=True),
    sa.Column('workflow_type', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.String(length=2000), nullable=True),
    sa.Column('priority', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_staff_id', sa.Uuid(), nullable=True),
    sa.Column('assigned_staff_id', sa.Uuid(), nullable=True),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completion_notes', sa.String(length=2000), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)", name=op.f('ck_workflow_tasks_cancellation_matches_status')),
    sa.CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name=op.f('ck_workflow_tasks_completion_matches_status')),
    sa.CheckConstraint("(status NOT IN ('ASSIGNED', 'IN_PROGRESS', 'COMPLETED') OR assigned_staff_id IS NOT NULL) AND (assigned_staff_id IS NULL) = (assigned_at IS NULL)", name=op.f('ck_workflow_tasks_assignment_matches_status')),
    sa.CheckConstraint("priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')", name=op.f('ck_workflow_tasks_priority_valid')),
    sa.CheckConstraint("status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')", name=op.f('ck_workflow_tasks_status_valid')),
    sa.CheckConstraint("workflow_type IN ('SAMPLE_COLLECTION', 'MEDICATION_ADMINISTRATION', 'NURSING_CARE', 'PATIENT_TRANSPORT', 'DISCHARGE_PREPARATION', 'FOLLOW_UP', 'ADMINISTRATIVE', 'OTHER')", name=op.f('ck_workflow_tasks_workflow_type_valid')),
    sa.CheckConstraint('length(btrim(title)) > 0', name=op.f('ck_workflow_tasks_title_not_blank')),
    sa.ForeignKeyConstraint(['assigned_staff_id'], ['staff.id'], name=op.f('fk_workflow_tasks_assigned_staff_id_staff'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['created_by_staff_id'], ['staff.id'], name=op.f('fk_workflow_tasks_created_by_staff_id_staff'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_workflow_tasks_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_workflow_tasks_patient_id_patients'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_tasks'))
    )
    op.create_index('ix_workflow_tasks_assigned_staff_id_status', 'workflow_tasks', ['assigned_staff_id', 'status'], unique=False)
    op.create_index('ix_workflow_tasks_patient_id', 'workflow_tasks', ['patient_id'], unique=False)
    op.create_index('ix_workflow_tasks_status_priority', 'workflow_tasks', ['status', 'priority'], unique=False)
    op.create_table('admissions',
    sa.Column('department_id', sa.Uuid(), nullable=False),
    sa.Column('bed', sa.String(length=30), nullable=True),
    sa.Column('encounter_id', sa.Uuid(), nullable=True),
    sa.Column('admission_type', sa.String(length=10), nullable=False),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('requested_by_staff_id', sa.Uuid(), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('approved_by_staff_id', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attending_staff_id', sa.Uuid(), nullable=True),
    sa.Column('admitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discharged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discharge_disposition', sa.String(length=30), nullable=True),
    sa.Column('discharge_summary', sa.Text(), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("(approved_at IS NULL) = (approved_by_staff_id IS NULL) AND ((status = 'REQUESTED') = (approved_at IS NULL) OR status = 'CANCELLED')", name=op.f('ck_admissions_approval_matches_status')),
    sa.CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)", name=op.f('ck_admissions_cancellation_matches_status')),
    sa.CheckConstraint("(status = 'DISCHARGED') = (discharged_at IS NOT NULL AND discharge_disposition IS NOT NULL)", name=op.f('ck_admissions_discharge_matches_status')),
    sa.CheckConstraint("(status IN ('ADMITTED', 'TRANSFERRED', 'DISCHARGED')) = (admitted_at IS NOT NULL AND encounter_id IS NOT NULL)", name=op.f('ck_admissions_admission_matches_status')),
    sa.CheckConstraint("admission_type IN ('ELECTIVE', 'EMERGENCY')", name=op.f('ck_admissions_admission_type_valid')),
    sa.CheckConstraint("discharge_disposition IS NULL OR discharge_disposition IN ('HOME', 'REFERRED_OUT', 'AGAINST_MEDICAL_ADVICE', 'DECEASED', 'OTHER')", name=op.f('ck_admissions_discharge_disposition_valid')),
    sa.CheckConstraint("status IN ('REQUESTED', 'APPROVED', 'ADMITTED', 'TRANSFERRED', 'DISCHARGED', 'CANCELLED')", name=op.f('ck_admissions_status_valid')),
    sa.CheckConstraint('(approved_at IS NULL OR approved_at >= requested_at) AND (admitted_at IS NULL OR admitted_at >= requested_at) AND (discharged_at IS NULL OR discharged_at >= admitted_at)', name=op.f('ck_admissions_timestamps_ordered')),
    sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_admissions_reason_not_blank')),
    sa.ForeignKeyConstraint(['approved_by_staff_id'], ['staff.id'], name=op.f('fk_admissions_approved_by_staff_id_staff'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['attending_staff_id'], ['staff.id'], name=op.f('fk_admissions_attending_staff_id_staff'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_admissions_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['encounter_id', 'patient_id'], ['encounters.id', 'encounters.patient_id'], name=op.f('fk_admissions_encounter_id_encounters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_admissions_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['requested_by_staff_id'], ['staff.id'], name=op.f('fk_admissions_requested_by_staff_id_staff'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admissions')),
    sa.UniqueConstraint('id', 'patient_id', name='uq_admissions_id_patient_id')
    )
    op.create_index('ix_admissions_department_id_status', 'admissions', ['department_id', 'status'], unique=False)
    op.create_index('ix_admissions_patient_id_requested_at', 'admissions', ['patient_id', 'requested_at'], unique=False)
    op.create_index('uq_admissions_one_open_per_patient', 'admissions', ['patient_id'], unique=True, postgresql_where=sa.text("status IN ('REQUESTED', 'APPROVED', 'ADMITTED', 'TRANSFERRED')"))
    op.create_table('appointments',
    sa.Column('department_id', sa.Uuid(), nullable=False),
    sa.Column('staff_id', sa.Uuid(), nullable=True),
    sa.Column('encounter_id', sa.Uuid(), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.String(length=1000), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('checked_in_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consultation_started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('no_show_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancellation_reason', sa.String(length=500), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL AND cancellation_reason IS NOT NULL)", name=op.f('ck_appointments_cancellation_matches_status')),
    sa.CheckConstraint("(status = 'COMPLETED') = (completed_at IS NOT NULL)", name=op.f('ck_appointments_completion_matches_status')),
    sa.CheckConstraint("(status = 'NO_SHOW') = (no_show_at IS NOT NULL)", name=op.f('ck_appointments_no_show_matches_status')),
    sa.CheckConstraint("(status IN ('IN_CONSULTATION', 'COMPLETED')) = (encounter_id IS NOT NULL)", name=op.f('ck_appointments_encounter_matches_status')),
    sa.CheckConstraint("status IN ('REQUESTED', 'CONFIRMED', 'CHECKED_IN', 'IN_CONSULTATION', 'COMPLETED', 'CANCELLED', 'NO_SHOW')", name=op.f('ck_appointments_status_valid')),
    sa.CheckConstraint('duration_minutes BETWEEN 5 AND 480', name=op.f('ck_appointments_duration_valid')),
    sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_appointments_reason_not_blank')),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], name=op.f('fk_appointments_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['encounter_id', 'patient_id'], ['encounters.id', 'encounters.patient_id'], name=op.f('fk_appointments_encounter_id_encounters'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_appointments_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], name=op.f('fk_appointments_staff_id_staff'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_appointments'))
    )
    op.create_index('ix_appointments_department_id_scheduled_start', 'appointments', ['department_id', 'scheduled_start'], unique=False)
    op.create_index('ix_appointments_patient_id_scheduled_start', 'appointments', ['patient_id', 'scheduled_start'], unique=False)
    op.create_index('ix_appointments_staff_id_scheduled_start', 'appointments', ['staff_id', 'scheduled_start'], unique=False)
    op.create_index('ix_appointments_status', 'appointments', ['status'], unique=False)
    op.create_table('admission_transfers',
    sa.Column('admission_id', sa.Uuid(), nullable=False),
    sa.Column('from_department_id', sa.Uuid(), nullable=False),
    sa.Column('to_department_id', sa.Uuid(), nullable=False),
    sa.Column('from_bed', sa.String(length=30), nullable=True),
    sa.Column('to_bed', sa.String(length=30), nullable=True),
    sa.Column('reason', sa.String(length=500), nullable=False),
    sa.Column('transferred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('transferred_by_staff_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('patient_id', sa.Uuid(), nullable=False),
    sa.CheckConstraint('from_department_id <> to_department_id OR from_bed IS DISTINCT FROM to_bed', name=op.f('ck_admission_transfers_location_changes')),
    sa.CheckConstraint('length(btrim(reason)) > 0', name=op.f('ck_admission_transfers_reason_not_blank')),
    sa.ForeignKeyConstraint(['admission_id', 'patient_id'], ['admissions.id', 'admissions.patient_id'], name=op.f('fk_admission_transfers_admission_id_admissions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['from_department_id'], ['departments.id'], name=op.f('fk_admission_transfers_from_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], name=op.f('fk_admission_transfers_patient_id_patients'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['to_department_id'], ['departments.id'], name=op.f('fk_admission_transfers_to_department_id_departments'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['transferred_by_staff_id'], ['staff.id'], name=op.f('fk_admission_transfers_transferred_by_staff_id_staff'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admission_transfers'))
    )
    op.create_index('ix_admission_transfers_admission_id', 'admission_transfers', ['admission_id'], unique=False)
    op.create_index('ix_admission_transfers_patient_id_transferred_at', 'admission_transfers', ['patient_id', 'transferred_at'], unique=False)
    op.add_column('clinical_notes', sa.Column('author_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_clinical_notes_author_staff_id_staff'), 'clinical_notes', 'staff', ['author_staff_id'], ['id'], ondelete='RESTRICT')
    op.add_column('encounters', sa.Column('attending_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_encounters_attending_staff_id_staff'), 'encounters', 'staff', ['attending_staff_id'], ['id'], ondelete='RESTRICT')
    op.add_column('lab_orders', sa.Column('ordered_by_staff_id', sa.Uuid(), nullable=True))
    op.add_column('lab_orders', sa.Column('verified_by_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_lab_orders_verified_by_staff_id_staff'), 'lab_orders', 'staff', ['verified_by_staff_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_lab_orders_ordered_by_staff_id_staff'), 'lab_orders', 'staff', ['ordered_by_staff_id'], ['id'], ondelete='RESTRICT')
    op.add_column('lab_results', sa.Column('entered_by_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_lab_results_entered_by_staff_id_staff'), 'lab_results', 'staff', ['entered_by_staff_id'], ['id'], ondelete='RESTRICT')
    op.add_column('lab_samples', sa.Column('collected_by_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_lab_samples_collected_by_staff_id_staff'), 'lab_samples', 'staff', ['collected_by_staff_id'], ['id'], ondelete='RESTRICT')
    op.add_column('prescriptions', sa.Column('prescriber_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_prescriptions_prescriber_staff_id_staff'), 'prescriptions', 'staff', ['prescriber_staff_id'], ['id'], ondelete='RESTRICT')
    op.add_column('reports', sa.Column('requested_by_staff_id', sa.Uuid(), nullable=True))
    op.add_column('reports', sa.Column('author_staff_id', sa.Uuid(), nullable=True))
    op.add_column('reports', sa.Column('verified_by_staff_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_reports_author_staff_id_staff'), 'reports', 'staff', ['author_staff_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_reports_verified_by_staff_id_staff'), 'reports', 'staff', ['verified_by_staff_id'], ['id'], ondelete='RESTRICT')
    op.create_foreign_key(op.f('fk_reports_requested_by_staff_id_staff'), 'reports', 'staff', ['requested_by_staff_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in STAFF_REFERENCES:
        op.drop_constraint(op.f(f'fk_{table}_{column}_staff'), table, type_='foreignkey')
        op.drop_column(table, column)
    op.drop_table('admission_transfers')
    op.drop_table('appointments')
    op.drop_table('admissions')
    op.drop_table('workflow_tasks')
    op.drop_table('staff')
    op.drop_table('departments')
