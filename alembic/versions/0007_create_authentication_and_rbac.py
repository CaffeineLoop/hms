"""create authentication and rbac

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-26 17:00:00.000000+00:00

Stage 5 — Authentication + Dynamic Roles & Permissions.

Tables: users (login account of one staff member), roles, permissions, role_permissions
(with scope ALL/OWN), user_roles, auth_sessions (only SHA-256 of tokens is stored).
No existing table changes.

Seed data (frozen here as literals so this migration never changes when the code catalog
evolves; later permissions arrive in later migrations):
- every permission of the Stage 5 catalog (app/core/permissions.py);
- default roles SUPER_ADMIN (system role, `is_superuser`: implicitly every permission),
  DOCTOR, NURSE, RECEPTIONIST, LAB_TECHNICIAN, PHARMACIST with their default grants.
No user accounts are created: the first administrator is created with
`python -m app.cli create-admin` (password read from a prompt or environment variable).

Generated with `alembic.autogenerate` for the Stage 5 models (boolean default corrected to
`false`), seeds added by hand. Downgrade drops the Stage 5 tables (and thus the seeds).
Destructive (downgrade) testing is done on hms_test only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (code, description)
PERMISSIONS = [
    ('patient.view', 'View and search patients'),
    ('patient.create', 'Register patients'),
    ('patient.edit', 'Edit patient details, deactivate/reactivate patients'),
    ('encounter.view', 'View encounters'),
    ('encounter.create', 'Open or document encounters'),
    ('encounter.edit', 'Start, finish or cancel encounters'),
    ('observation.view', 'View observations and vital signs'),
    ('observation.create', 'Record observations and vital signs'),
    ('condition.view', 'View conditions'),
    ('condition.create', 'Document conditions'),
    ('condition.edit', 'Change condition status'),
    ('allergy.view', 'View allergies'),
    ('allergy.create', 'Document allergies'),
    ('allergy.edit', 'Update allergies'),
    ('clinical_note.view', 'Read clinical notes'),
    ('clinical_note.create', 'Write clinical notes'),
    ('timeline.view', 'View the patient timeline (events limited to the other view permissions held)'),
    ('lab.view', 'View lab orders, samples and results'),
    ('lab.order', 'Order and cancel lab tests'),
    ('lab.collect', 'Record sample collection'),
    ('lab.process', 'Process samples, enter and correct results'),
    ('lab.verify', 'Verify and release lab results'),
    ('report.view', 'View reports'),
    ('report.create', 'Create, edit and cancel draft reports'),
    ('report.verify', 'Verify and release reports'),
    ('prescription.view', 'View prescriptions'),
    ('prescription.create', 'Write, edit and issue prescriptions'),
    ('prescription.edit', 'Hold, resume, complete or cancel prescriptions'),
    ('staff.view', 'View departments and staff'),
    ('staff.manage', 'Manage departments and staff'),
    ('appointment.view', 'View appointments'),
    ('appointment.manage', 'Book and progress appointments'),
    ('admission.view', 'View admissions'),
    ('admission.manage', 'Request, approve, admit, transfer and discharge'),
    ('workflow.view', 'View workflow tasks'),
    ('workflow.manage', 'Create, assign and progress workflow tasks'),
    ('user.view', 'View user accounts'),
    ('user.manage', 'Create/deactivate user accounts, reset passwords, assign roles'),
    ('role.manage', 'Create, edit and deactivate roles'),
    ('permission.manage', 'Grant and revoke role permissions'),
    ('audit.view', 'View audit trails (reserved for Stage 6)'),
    ('ai.analysis', 'Run AI analysis (reserved for a later stage)'),
    ('ai.review', 'Review AI output (reserved for a later stage)'),
]

# (name, description, is_superuser, [(permission code, scope), ...])
ROLES = [
    ('SUPER_ADMIN', 'System administrator: every permission (system role, cannot be edited)', True, []),
    ('DOCTOR', 'Clinician: full clinical documentation, orders and prescriptions', False, [('admission.manage', 'ALL'), ('admission.view', 'ALL'), ('allergy.create', 'ALL'), ('allergy.edit', 'ALL'), ('allergy.view', 'ALL'), ('appointment.manage', 'ALL'), ('appointment.view', 'ALL'), ('clinical_note.create', 'ALL'), ('clinical_note.view', 'ALL'), ('condition.create', 'ALL'), ('condition.edit', 'ALL'), ('condition.view', 'ALL'), ('encounter.create', 'ALL'), ('encounter.edit', 'ALL'), ('encounter.view', 'ALL'), ('lab.order', 'ALL'), ('lab.view', 'ALL'), ('observation.create', 'ALL'), ('observation.view', 'ALL'), ('patient.create', 'ALL'), ('patient.edit', 'ALL'), ('patient.view', 'ALL'), ('prescription.create', 'ALL'), ('prescription.edit', 'ALL'), ('prescription.view', 'ALL'), ('report.create', 'ALL'), ('report.verify', 'ALL'), ('report.view', 'ALL'), ('staff.view', 'ALL'), ('timeline.view', 'ALL'), ('workflow.manage', 'ALL'), ('workflow.view', 'ALL')]),
    ('NURSE', 'Nursing: observations, notes, sample collection, own tasks', False, [('admission.manage', 'ALL'), ('admission.view', 'ALL'), ('allergy.create', 'ALL'), ('allergy.view', 'ALL'), ('appointment.manage', 'ALL'), ('appointment.view', 'ALL'), ('clinical_note.create', 'ALL'), ('clinical_note.view', 'ALL'), ('condition.view', 'ALL'), ('encounter.view', 'ALL'), ('lab.collect', 'ALL'), ('lab.view', 'ALL'), ('observation.create', 'ALL'), ('observation.view', 'ALL'), ('patient.view', 'ALL'), ('prescription.view', 'ALL'), ('report.view', 'ALL'), ('staff.view', 'ALL'), ('timeline.view', 'ALL'), ('workflow.manage', 'OWN'), ('workflow.view', 'OWN')]),
    ('RECEPTIONIST', 'Front desk: registration and appointments', False, [('admission.view', 'ALL'), ('appointment.manage', 'ALL'), ('appointment.view', 'ALL'), ('patient.create', 'ALL'), ('patient.edit', 'ALL'), ('patient.view', 'ALL'), ('staff.view', 'ALL')]),
    ('LAB_TECHNICIAN', 'Laboratory: samples, processing, result entry, lab reports', False, [('lab.collect', 'ALL'), ('lab.process', 'ALL'), ('lab.view', 'ALL'), ('patient.view', 'ALL'), ('report.create', 'ALL'), ('report.view', 'ALL'), ('staff.view', 'ALL')]),
    ('PHARMACIST', 'Pharmacy: review and progress prescriptions', False, [('allergy.view', 'ALL'), ('patient.view', 'ALL'), ('prescription.edit', 'ALL'), ('prescription.view', 'ALL'), ('staff.view', 'ALL')]),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('permissions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("code ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'", name=op.f('ck_permissions_code_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_permissions')),
    sa.UniqueConstraint('code', name=op.f('uq_permissions_code'))
    )
    op.create_table('roles',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('is_superuser', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("name ~ '^[A-Z][A-Z0-9_]{1,49}$'", name=op.f('ck_roles_name_format')),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f('ck_roles_status_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
    sa.UniqueConstraint('name', name=op.f('uq_roles_name'))
    )
    op.create_table('users',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('staff_id', sa.Uuid(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('password_changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'INACTIVE') = (deactivated_at IS NOT NULL)", name=op.f('ck_users_deactivation_matches_status')),
    sa.CheckConstraint("password_hash LIKE 'scrypt$%'", name=op.f('ck_users_password_hash_format')),
    sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f('ck_users_status_valid')),
    sa.CheckConstraint("username ~ '^[a-z0-9][a-z0-9._-]{2,49}$'", name=op.f('ck_users_username_format')),
    sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], name=op.f('fk_users_staff_id_staff'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('staff_id', name=op.f('uq_users_staff_id')),
    sa.UniqueConstraint('username', name=op.f('uq_users_username'))
    )
    op.create_table('auth_sessions',
    sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name=op.f('ck_auth_sessions_token_hash_format')),
    sa.CheckConstraint('expires_at > created_at', name=op.f('ck_auth_sessions_expires_after_created')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_sessions_token_hash'))
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'], unique=False)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('permission_id', sa.Uuid(), nullable=False),
    sa.Column('scope', sa.String(length=10), server_default=sa.text("'ALL'"), nullable=False),
    sa.Column('granted_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("scope IN ('ALL', 'OWN')", name=op.f('ck_role_permissions_scope_valid')),
    sa.ForeignKeyConstraint(['granted_by_user_id'], ['users.id'], name=op.f('fk_role_permissions_granted_by_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], name=op.f('fk_role_permissions_permission_id_permissions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_role_permissions_role_id_roles'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id', name=op.f('pk_role_permissions'))
    )
    op.create_index('ix_role_permissions_permission_id', 'role_permissions', ['permission_id'], unique=False)
    op.create_table('user_roles',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('role_id', sa.Uuid(), nullable=False),
    sa.Column('assigned_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by_user_id'], ['users.id'], name=op.f('fk_user_roles_assigned_by_user_id_users'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], name=op.f('fk_user_roles_role_id_roles'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_roles_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id', name=op.f('pk_user_roles'))
    )
    op.create_index('ix_user_roles_role_id', 'user_roles', ['role_id'], unique=False)

    permissions = sa.table('permissions', sa.column('code', sa.String), sa.column('description', sa.String))
    op.bulk_insert(permissions, [{'code': code, 'description': description} for code, description in PERMISSIONS])
    roles = sa.table('roles', sa.column('name', sa.String), sa.column('description', sa.String),
                     sa.column('status', sa.String), sa.column('is_superuser', sa.Boolean))
    op.bulk_insert(roles, [
        {'name': name, 'description': description, 'status': 'ACTIVE', 'is_superuser': superuser}
        for name, description, superuser, _ in ROLES
    ])
    connection = op.get_bind()
    for name, _, _, grants in ROLES:
        for code, scope in grants:
            connection.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id, scope) "
                    "SELECT r.id, p.id, :scope FROM roles r, permissions p WHERE r.name = :role AND p.code = :code"
                ),
                {'role': name, 'code': code, 'scope': scope},
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_table('auth_sessions')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('permissions')
