"""sub calendars

Revision ID: d2a6c40f8b17
Revises: c9e0f27b3d55
Create Date: 2026-08-11

A connected account holds several calendars, and users expect to choose which
ones count. This splits the single implicit "primary" calendar out into a
`calendars` table, moves per-calendar sync state and the school/work/personal
kind onto it, and repoints imported events at it.

Existing connections are backfilled with one row standing for the primary
calendar they were already importing, so no imported event is lost. Google's
primary calendar id is the account's email address, which is what the next
calendar-list refresh will match on.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2a6c40f8b17'
down_revision: Union[str, Sequence[str], None] = 'c9e0f27b3d55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND = sa.Enum('school', 'work', 'personal', name='calendar_kind',
                native_enum=False, create_constraint=True)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'calendars',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('calendar_connection_id', sa.Integer(), nullable=False),
        sa.Column('provider_calendar_id', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.String(length=20), nullable=True),
        sa.Column('is_primary', sa.Boolean(),
                  server_default=sa.text('false'), nullable=False),
        sa.Column('selected', sa.Boolean(),
                  server_default=sa.text('true'), nullable=False),
        sa.Column('kind', _KIND, server_default='personal', nullable=False),
        sa.Column('sync_token', sa.Text(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['calendar_connection_id'],
                                ['calendar_connections.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('calendar_connection_id', 'provider_calendar_id'),
    )
    op.create_index(op.f('ix_calendars_calendar_connection_id'), 'calendars',
                    ['calendar_connection_id'])

    # One calendar per existing connection, standing for the primary calendar
    # that was being imported implicitly. Carries over that connection's kind
    # and sync token so the next sync stays incremental.
    op.execute("""
        INSERT INTO calendars (
            calendar_connection_id, provider_calendar_id, name, is_primary,
            selected, kind, sync_token, last_synced_at, last_sync_error
        )
        SELECT id,
               COALESCE(account_email, 'primary'),
               COALESCE(account_email, 'Primary calendar'),
               true, true, kind, sync_token, last_synced_at, last_sync_error
        FROM calendar_connections
    """)

    op.add_column('events', sa.Column('calendar_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_events_calendar_id'), 'events', ['calendar_id'])
    op.create_foreign_key('fk_events_calendar_id', 'events', 'calendars',
                          ['calendar_id'], ['id'], ondelete='CASCADE')

    # Repoint imported events at the backfilled calendar of their connection.
    op.execute("""
        UPDATE events SET calendar_id = c.id
        FROM calendars c
        WHERE c.calendar_connection_id = events.calendar_connection_id
    """)

    op.drop_constraint('uq_events_provider_event', 'events', type_='unique')
    op.drop_column('events', 'calendar_connection_id')
    op.create_unique_constraint('uq_events_provider_event', 'events',
                                ['calendar_id', 'provider_event_id'])

    op.drop_column('calendar_connections', 'sync_token')
    op.alter_column('calendar_connections', 'kind', new_column_name='default_kind')


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('calendar_connections', 'default_kind', new_column_name='kind')
    op.add_column('calendar_connections', sa.Column('sync_token', sa.Text(),
                                                    nullable=True))
    op.execute("""
        UPDATE calendar_connections SET sync_token = c.sync_token
        FROM calendars c
        WHERE c.calendar_connection_id = calendar_connections.id
          AND c.is_primary
    """)

    op.add_column('events', sa.Column('calendar_connection_id', sa.Integer(),
                                      nullable=True))
    op.execute("""
        UPDATE events SET calendar_connection_id = c.calendar_connection_id
        FROM calendars c WHERE c.id = events.calendar_id
    """)
    op.create_index(op.f('ix_events_calendar_connection_id'), 'events',
                    ['calendar_connection_id'])
    op.create_foreign_key('fk_events_calendar_connection_id', 'events',
                          'calendar_connections', ['calendar_connection_id'],
                          ['id'], ondelete='CASCADE')

    op.drop_constraint('uq_events_provider_event', 'events', type_='unique')
    op.drop_constraint('fk_events_calendar_id', 'events', type_='foreignkey')
    op.drop_index(op.f('ix_events_calendar_id'), table_name='events')
    op.drop_column('events', 'calendar_id')
    op.create_unique_constraint('uq_events_provider_event', 'events',
                                ['calendar_connection_id', 'provider_event_id'])

    op.drop_index(op.f('ix_calendars_calendar_connection_id'),
                  table_name='calendars')
    op.drop_table('calendars')
