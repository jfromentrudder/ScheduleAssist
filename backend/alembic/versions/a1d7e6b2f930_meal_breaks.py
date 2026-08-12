"""meal breaks

Revision ID: a1d7e6b2f930
Revises: f6c3a95e40d8
Create Date: 2026-08-11

The generator now holds time clear for a meal, which needs two things: a way
to mark a generated block as a break rather than work, and a way for the user
to say "this is my lunch" so the generator leaves that day alone.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1d7e6b2f930'
down_revision: Union[str, Sequence[str], None] = 'f6c3a95e40d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AVAILABILITY = "availability IN ('busy', 'free', 'work_window', 'meal')"
_AVAILABILITY_OLD = "availability IN ('busy', 'free', 'work_window')"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'periods',
        sa.Column(
            'kind',
            sa.Enum('work', 'meal', name='period_kind', native_enum=False,
                    create_constraint=True),
            server_default='work', nullable=False,
        ),
    )

    # The availability enum is VARCHAR + CHECK, so widening it is a constraint
    # swap rather than an ALTER TYPE.
    op.drop_constraint('availability', 'events', type_='check')
    op.create_check_constraint('availability', 'events', _AVAILABILITY)


def downgrade() -> None:
    """Downgrade schema."""
    # Anything marked as a meal becomes ordinary busy time, which is how it
    # behaved before this revision.
    op.execute("UPDATE events SET availability = 'busy' "
               "WHERE availability = 'meal'")
    op.drop_constraint('availability', 'events', type_='check')
    op.create_check_constraint('availability', 'events', _AVAILABILITY_OLD)

    op.drop_column('periods', 'kind')
