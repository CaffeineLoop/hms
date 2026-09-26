"""ai assistant permission

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27 09:00:00.000000+00:00

Stage 7 — AI Assistant Foundation. Data-only: `ai.analysis` (seeded in 0007 as reserved) is now
enforced by the AI endpoints; its description is updated. No schema changes and no role grants
(administrators decide who may use the assistant). The assistant stores no AI output: requests
are recorded in the existing audit trail (0008).
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE permissions SET description = 'Use the read-only AI clinical-analysis assistant' "
               "WHERE code = 'ai.analysis'")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("UPDATE permissions SET description = 'Run AI analysis (reserved for a later stage)' "
               "WHERE code = 'ai.analysis'")
