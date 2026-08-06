"""baseline - current schema snapshot

Revision ID: 84ea41eb1f25
Revises:
Create Date: 2026-08-06 18:57:31.722413

This is a no-op baseline revision.
The DB schema and ORM models are already in sync.
Alembic autogenerate detected minor cosmetic differences (JSON vs Text,
server defaults, index naming) but the actual DB state is correct.
Future migrations should start from this revision.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '84ea41eb1f25'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Baseline - no structural changes needed."""
    pass


def downgrade() -> None:
    """Baseline - no structural changes needed."""
    pass
