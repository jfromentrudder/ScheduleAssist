"""user preference bounds

Revision ID: f6c3a95e40d8
Revises: e4b8d1097c62
Create Date: 2026-08-11

Adds the meal-break preference and puts CHECK constraints behind the
preferences the settings screen now exposes. The bounds mirror the constants
in app/scheduler.py, so the database refuses anything the API would have.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6c3a95e40d8'
down_revision: Union[str, Sequence[str], None] = 'e4b8d1097c62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('lunch_minutes', sa.Integer(),
                  server_default=sa.text('60'), nullable=False),
    )

    # Clamp anything already outside the new bounds, so adding the constraints
    # cannot fail on existing rows.
    op.execute("UPDATE users SET period_minutes = 15 WHERE period_minutes < 15")
    op.execute("UPDATE users SET period_minutes = 240 WHERE period_minutes > 240")
    op.execute("UPDATE users SET day_end = '17:00' WHERE day_end <= day_start")

    op.create_check_constraint(
        'ck_users_period_range', 'users',
        'period_minutes BETWEEN 15 AND 240')
    op.create_check_constraint(
        'ck_users_lunch_range', 'users',
        'lunch_minutes BETWEEN 30 AND 120')
    op.create_check_constraint(
        'ck_users_day_bounds', 'users', 'day_end > day_start')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_users_day_bounds', 'users', type_='check')
    op.drop_constraint('ck_users_lunch_range', 'users', type_='check')
    op.drop_constraint('ck_users_period_range', 'users', type_='check')
    op.drop_column('users', 'lunch_minutes')
