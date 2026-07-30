"""
SQLAlchemy ORM models.
"""

import enum

from app.crypto import EncryptedString
from app.database import Base  # noqa: F401
from datetime import datetime, time
from sqlalchemy import (
    CheckConstraint, Column, DateTime, Enum, ForeignKey, Index, String, Table,
    Text, Time, UniqueConstraint, func, text, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship


class Theme(str, enum.Enum):
    """Colour palettes a user can pick in settings. All share one block grammar."""

    EMBER = "ember"          # default: cool slate, amber reserved for periods
    TIDE = "tide"
    MERIDIAN = "meridian"
    GRAPHITE = "graphite"
    DAYLIGHT = "daylight"
    SIGNAL = "signal"


class Appearance(str, enum.Enum):
    """Light/dark choice. SYSTEM defers to the browser."""

    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


_THEME = Enum(Theme, name="theme", native_enum=False, create_constraint=True,
              values_callable=lambda e: [m.value for m in e])
_APPEARANCE = Enum(Appearance, name="appearance", native_enum=False,
                   create_constraint=True,
                   values_callable=lambda e: [m.value for m in e])


class EventType(str, enum.Enum):
    """What kind of thing an event is, from the scheduler's point of view."""

    # A due date. The engine allocates prep periods *before* it.
    DEADLINE = "deadline"
    # A fixed block of busy time (class, meeting). The engine schedules *around* it.
    ONE_TIME = "one_time"


class EventSource(str, enum.Enum):
    IMPORTED = "imported"  # pulled from a connected calendar
    MANUAL = "manual"      # created in ScheduleAssist


# Stored as VARCHAR + CHECK rather than a native Postgres ENUM, so adding a
# value later is an ordinary migration instead of an ALTER TYPE dance.
# create_constraint must be set explicitly: SQLAlchemy defaults it to False,
# which would leave the column a bare VARCHAR accepting any short string.
_EVENT_TYPE = Enum(EventType, name="event_type", native_enum=False,
                   create_constraint=True,
                   values_callable=lambda e: [m.value for m in e])
_EVENT_SOURCE = Enum(EventSource, name="event_source", native_enum=False,
                     create_constraint=True,
                     values_callable=lambda e: [m.value for m in e])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    identities: Mapped[list["AuthIdentity"]
                       ] = relationship(back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    # Calendars attach to the user, not to a sign-in identity, so a user who
    # signed in with any provider can still connect a Google calendar.
    calendar_connections: Mapped[list["CalendarConnection"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    events: Mapped[list["Event"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)
    periods: Mapped[list["Period"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True)

    # --- Scheduling preferences. The generator reads these directly. ---
    # Days the user is willing to work, as ISO weekday numbers (Monday = 0).
    workdays: Mapped[list[int]] = mapped_column(
        JSON, default=lambda: [0, 1, 2, 3, 4],
        server_default=text("'[0, 1, 2, 3, 4]'"))
    # Earliest and latest wall-clock times a period may occupy, same every workday.
    day_start: Mapped[time] = mapped_column(
        Time, default=time(9, 0), server_default=text("'09:00'"))
    day_end: Mapped[time] = mapped_column(
        Time, default=time(17, 0), server_default=text("'17:00'"))
    # Length of one generated work period.
    period_minutes: Mapped[int] = mapped_column(
        default=50, server_default=text("50"))
    # The wall-clock times above are meaningless without a zone: 09:00 is a
    # different instant in Corvallis than in UTC. Everything else is stored UTC.
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC")

    # --- Appearance. Stored per user so it follows them between devices. ---
    theme: Mapped[Theme] = mapped_column(
        _THEME, default=Theme.EMBER, server_default=Theme.EMBER.value)
    appearance: Mapped[Appearance] = mapped_column(
        _APPEARANCE, default=Appearance.SYSTEM,
        server_default=Appearance.SYSTEM.value)


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_subject: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str | None]

    user: Mapped[User] = relationship(back_populates="identities")


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True)


class CalendarConnection(Base):
    """A calendar account the user has authorized us to read.

    Separate from AuthIdentity on purpose: signing in with Google and granting
    calendar access are two different consents, and a user may connect several
    calendar accounts (or a provider they did not sign in with).
    """

    __tablename__ = "calendar_connections"
    # A user may hold many connections, but only one per provider account.
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "provider_account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)

    provider: Mapped[str] = mapped_column(
        String(20))  # "google", later "microsoft"
    # Stable account id from the provider; the email can change, this will not.
    provider_account_id: Mapped[str] = mapped_column(String(255))
    # Shown in the UI so the user can tell two connected accounts apart.
    account_email: Mapped[str | None] = mapped_column(String(255))

    # Encrypted at rest — see app/crypto.py. The refresh token is nullable
    # because Google only returns one on the first consent for a given account.
    access_token: Mapped[str] = mapped_column(EncryptedString)
    refresh_token: Mapped[str | None] = mapped_column(EncryptedString)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    # Space-delimited scopes actually granted, which may be fewer than requested.
    scopes: Mapped[str] = mapped_column(Text, default="")

    # Sync state, written by the import job.
    sync_token: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="calendar_connections")

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes.split()


# A period can serve several events (one study block covering two deadlines),
# and an event's prep can span several periods — hence many-to-many.
period_events = Table(
    "period_events",
    Base.metadata,
    Column("period_id", ForeignKey("periods.id", ondelete="CASCADE"),
           primary_key=True),
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"),
           primary_key=True),
)


class Event(Base):
    """Something on the user's schedule: a deadline to work toward, or a fixed
    block of busy time to schedule around."""

    __tablename__ = "events"
    __table_args__ = (
        # A one-time event occupies a span; a deadline is a single moment.
        # Enforced in the database so the generator can trust the shape.
        CheckConstraint(
            "(event_type = 'one_time'"
            "  AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND due_at IS NULL)"
            " OR (event_type = 'deadline'"
            "  AND due_at IS NOT NULL AND starts_at IS NULL AND ends_at IS NULL)",
            name="ck_events_times_match_type",
        ),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at",
                        name="ck_events_end_after_start"),
        CheckConstraint(
            "expected_prep_minutes IS NULL OR expected_prep_minutes > 0",
            name="ck_events_prep_positive"),
        # De-duplicates re-imports. Manual events leave both columns NULL, and
        # Postgres treats NULLs as distinct, so they are unaffected.
        UniqueConstraint("calendar_connection_id", "provider_event_id",
                         name="uq_events_provider_event"),
        # The schedule view and generator both query a user's date range.
        Index("ix_events_user_starts_at", "user_id", "starts_at"),
        Index("ix_events_user_due_at", "user_id", "due_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)

    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[EventType] = mapped_column(_EVENT_TYPE)
    source: Mapped[EventSource] = mapped_column(_EVENT_SOURCE)

    # Populated per event_type; see the CHECK constraint above.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_all_day: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"))

    # How much work the user expects this to take. Drives how many periods the
    # generator allocates; NULL means "no prep needed" (e.g. a plain meeting).
    expected_prep_minutes: Mapped[int | None] = mapped_column()

    # Set only for imported events. CASCADE means disconnecting a calendar
    # removes the events it brought in.
    calendar_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="CASCADE"), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="events")
    periods: Mapped[list["Period"]] = relationship(
        secondary=period_events, back_populates="events")


class Period(Base):
    """A generated work block. Derived data: regeneration replaces these."""

    __tablename__ = "periods"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_periods_end_after_start"),
        Index("ix_periods_user_starts_at", "user_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)

    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="periods")
    events: Mapped[list[Event]] = relationship(
        secondary=period_events, back_populates="periods")
