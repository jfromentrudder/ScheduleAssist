"""user schedule horizon

Revision ID: a3f1c92d5e40
Revises: 0e215572b017
Create Date: 2026-08-07

Adds the commitment horizon: how many days ahead (counting today) a user's
schedule is treated as settled. Existing users get the 5-day default, which
matches a standard work week.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f1c92d5e40'
down_revision: Union[str, Sequence[str], None] = '0e215572b017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('schedule_horizon_days', sa.Integer(),
                  server_default=sa.text('5'), nullable=False),
    )
    op.create_check_constraint(
        'ck_users_horizon_range', 'users',
        'schedule_horizon_days BETWEEN 1 AND 21',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_users_horizon_range', 'users', type_='check')
    op.drop_column('users', 'schedule_horizon_days')
