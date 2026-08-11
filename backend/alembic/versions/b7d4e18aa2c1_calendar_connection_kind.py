"""calendar connection kind

Revision ID: b7d4e18aa2c1
Revises: a3f1c92d5e40
Create Date: 2026-08-10

Records whether a connected calendar is a school, work or personal one. The
distinction drives deadline inference: school calendars express assignments as
all-day events, work calendars do not. Existing connections become 'personal',
the conservative default that infers nothing.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4e18aa2c1'
down_revision: Union[str, Sequence[str], None] = 'a3f1c92d5e40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'calendar_connections',
        sa.Column(
            'kind',
            sa.Enum('school', 'work', 'personal', name='calendar_kind',
                    native_enum=False, create_constraint=True),
            server_default='personal', nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('calendar_connections', 'kind')
