"""event availability

Revision ID: e4b8d1097c62
Revises: d2a6c40f8b17
Create Date: 2026-08-11

Separates the three things an event's time can mean: occupied (schedule
around it), informational (ignore it), and available for work (fill it with
periods). A shift at work is the third, and there was previously no way to say
so — it read as a solid wall of busy time.

Backfilled to preserve existing behaviour exactly: timed events were treated as
busy and all-day events were ignored, so they become 'busy' and 'free'
respectively.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4b8d1097c62'
down_revision: Union[str, Sequence[str], None] = 'd2a6c40f8b17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'events',
        sa.Column(
            'availability',
            sa.Enum('busy', 'free', 'work_window', name='availability',
                    native_enum=False, create_constraint=True),
            server_default='busy', nullable=False,
        ),
    )
    # All-day events were never counted as busy time; keep it that way.
    op.execute("UPDATE events SET availability = 'free' WHERE is_all_day")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('events', 'availability')
