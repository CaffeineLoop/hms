"""patient identity integrity

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26 13:00:00.000000+00:00

Stage 2 pre-flight fixes to the Stage 1 patients table (0002 is left untouched):
- Rewrites any stored phone numbers using the '00' international prefix to '+' so that
  stored values match the application's deterministic normalization.
- Enforces the patient duplicate rule in PostgreSQL with two partial unique indexes:
  same case-insensitive first + last name and date of birth AND the same phone
  (uq_patients_identity_phone) or the same email (uq_patients_identity_email).

If existing rows already violate the rule, the upgrade fails (by design) rather than
silently keeping duplicates; they must be merged or corrected first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME_DOB = [sa.literal_column('lower(last_name)'), sa.literal_column('lower(first_name)'), 'date_of_birth']


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE patients SET phone = '+' || substr(phone, 3) WHERE phone LIKE '00%'")
    op.execute(
        "UPDATE patients SET emergency_contact_phone = '+' || substr(emergency_contact_phone, 3)"
        " WHERE emergency_contact_phone LIKE '00%'"
    )
    op.create_index(
        'uq_patients_identity_phone',
        'patients',
        [*_NAME_DOB, 'phone'],
        unique=True,
        postgresql_where=sa.text('phone IS NOT NULL'),
    )
    op.create_index(
        'uq_patients_identity_email',
        'patients',
        [*_NAME_DOB, 'email'],
        unique=True,
        postgresql_where=sa.text('email IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema. The phone rewrite is a normalization and is not reversed."""
    op.drop_index('uq_patients_identity_email', table_name='patients')
    op.drop_index('uq_patients_identity_phone', table_name='patients')
