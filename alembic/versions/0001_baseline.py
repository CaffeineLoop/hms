"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-09-26 08:55:38.153358+00:00

Stage 0 baseline. Intentionally contains no schema changes: it anchors the
migration history so that every future domain table (Stage 1 onwards) is
introduced by its own reviewed revision on top of this one. Applying it only
records revision '0001' in Alembic's own `alembic_version` table.
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. No-op baseline."""
    pass


def downgrade() -> None:
    """Downgrade schema. No-op baseline."""
    pass
