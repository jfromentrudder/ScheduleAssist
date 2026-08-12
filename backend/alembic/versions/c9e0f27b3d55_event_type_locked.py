"""event type locked

Revision ID: c9e0f27b3d55
Revises: b7d4e18aa2c1
Create Date: 2026-08-11

Marks events whose type or prep estimate the user has corrected by hand, so a
later sync does not overwrite that decision with an inferred guess. Existing
events are unlocked: nothing has been corrected yet.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e0f27b3d55'
down_revision: Union[str, Sequence[str], None] = 'b7d4e18aa2c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'events',
        sa.Column('type_locked', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('events', 'type_locked')
