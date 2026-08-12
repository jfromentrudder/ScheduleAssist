"""
SQLAlchemy ORM models.
"""

import enum

from app.crypto import EncryptedString
from app.database import Base  # noqa: F401
from app.scheduler import (
    DEFAULT_HORIZON_DAYS, DEFAULT_LUNCH_MINUTES, MAX_HORIZON_DAYS,
    MAX_LUNCH_MINUTES, MAX_PERIOD_MINUTES, MIN_HORIZON_DAYS,
    MIN_LUNCH_MINUTES, MIN_PERIOD_MINUTES,
)
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


class CalendarKind(str, enum.Enum):
    """What sort of calendar a connection is, chosen by the user at connect time.

    This is not cosmetic: school calendars routinely express assignments as
    all-day events, so deadline inference reads them differently from work
    calendars. PERSONAL is the conservative default — no title inference.
    """

    SCHOOL = "school"
    WORK = "work"
    PERSONAL = "personal"


_CALENDAR_KIND = Enum(CalendarKind, name="calendar_kind", native_enum=False,
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


class Availability(str, enum.Enum):
    """What an event's time means for scheduling.

    The three answers are genuinely different, and collapsing them is what
    makes a naive scheduler useless: a meeting is time you cannot work, a
    reminder is not time at all, and a shift at work is precisely the time you
    *do* work — periods belong inside it, not around it.
    """

    # Occupied. The generator schedules around it.
    BUSY = "busy"
    # Informational. Neither blocks time nor offers any.
    FREE = "free"
    # Time available for work. The generator fills it with periods.
    WORK_WINDOW = "work_window"
    # A meal the user has placed themselves. Occupies time like BUSY, and
    # tells the generator not to reserve another break that day.
    MEAL = "meal"


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
_AVAILABILITY = Enum(Availability, name="availability", native_enum=False,
                     create_constraint=True,
                     values_callable=lambda e: [m.value for m in e])


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Bounds mirror the engine's constants so the database, the API and the
        # generator cannot drift apart on what a legal preference is.
        CheckConstraint(
            f"schedule_horizon_days BETWEEN {MIN_HORIZON_DAYS} AND {MAX_HORIZON_DAYS}",
            name="ck_users_horizon_range"),
        CheckConstraint(
            f"period_minutes BETWEEN {MIN_PERIOD_MINUTES} AND {MAX_PERIOD_MINUTES}",
            name="ck_users_period_range"),
        CheckConstraint(
            f"lunch_minutes BETWEEN {MIN_LUNCH_MINUTES} AND {MAX_LUNCH_MINUTES}",
            name="ck_users_lunch_range"),
        CheckConstraint("day_end > day_start", name="ck_users_day_bounds"),
    )

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
    # How long to leave clear for a meal in the middle of a working day.
    lunch_minutes: Mapped[int] = mapped_column(
        default=DEFAULT_LUNCH_MINUTES,
        server_default=text(str(DEFAULT_LUNCH_MINUTES)))
    # How many days ahead — counting today — the schedule is treated as
    # settled. Periods inside this horizon are not reshuffled when new events
    # arrive, because a plan that rearranges itself the night before is not a
    # plan. See app/scheduler.py for how it is applied.
    schedule_horizon_days: Mapped[int] = mapped_column(
        default=DEFAULT_HORIZON_DAYS,
        server_default=text(str(DEFAULT_HORIZON_DAYS)))
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
    # Applied to calendars discovered on this account. The value that actually
    # drives inference lives on each Calendar, because one account routinely
    # holds both a work calendar and a personal one.
    default_kind: Mapped[CalendarKind] = mapped_column(
        _CALENDAR_KIND, default=CalendarKind.PERSONAL,
        server_default=CalendarKind.PERSONAL.value)

    # Encrypted at rest — see app/crypto.py. The refresh token is nullable
    # because Google only returns one on the first consent for a given account.
    access_token: Mapped[str] = mapped_column(EncryptedString)
    refresh_token: Mapped[str | None] = mapped_column(EncryptedString)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    # Space-delimited scopes actually granted, which may be fewer than requested.
    scopes: Mapped[str] = mapped_column(Text, default="")

    # Account-level sync state. Per-calendar state lives on Calendar, since
    # Google issues a sync token per calendar, not per account.
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="calendar_connections")
    calendars: Mapped[list["Calendar"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan",
        passive_deletes=True)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes.split()


class Calendar(Base):
    """One calendar inside a connected account.

    A Google account is not a calendar: it holds several, and users expect to
    choose which ones count — the checkbox list in Google Calendar, or the
    account/sub-calendar tree in Apple's Calendar. Each is imported and
    interpreted independently, so `kind` lives here rather than on the account.
    """

    __tablename__ = "calendars"
    __table_args__ = (
        UniqueConstraint("calendar_connection_id", "provider_calendar_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    calendar_connection_id: Mapped[int] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="CASCADE"), index=True)

    # The provider's id for this calendar. For Google's primary calendar this
    # is the account's email address.
    provider_calendar_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    # The colour the provider shows it in, so the UI can match what the user
    # already recognises from Google or Apple.
    color: Mapped[str | None] = mapped_column(String(20))
    is_primary: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"))

    # Whether this calendar's events are imported at all. Unselecting removes
    # them: an unchecked calendar must not quietly block out work periods.
    selected: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"))
    kind: Mapped[CalendarKind] = mapped_column(
        _CALENDAR_KIND, default=CalendarKind.PERSONAL,
        server_default=CalendarKind.PERSONAL.value)

    # Sync state, per calendar because that is how Google issues sync tokens.
    sync_token: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True))
    last_sync_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    connection: Mapped[CalendarConnection] = relationship(
        back_populates="calendars")
    events: Mapped[list["Event"]] = relationship(
        back_populates="calendar", cascade="all, delete-orphan",
        passive_deletes=True)


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
        # De-duplicates re-imports. Keyed on the calendar rather than the
        # account, because provider event ids are only unique within one
        # calendar. Manual events leave both columns NULL, and Postgres treats
        # NULLs as distinct, so they are unaffected.
        UniqueConstraint("calendar_id", "provider_event_id",
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
    # How this event's span affects generation. Meaningless for deadlines,
    # which are moments rather than spans.
    availability: Mapped[Availability] = mapped_column(
        _AVAILABILITY, default=Availability.BUSY,
        server_default=Availability.BUSY.value)

    # Populated per event_type; see the CHECK constraint above.
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_all_day: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"))

    # How much work the user expects this to take. Drives how many periods the
    # generator allocates; NULL means "no prep needed" (e.g. a plain meeting).
    expected_prep_minutes: Mapped[int | None] = mapped_column()

    # Set only for imported events. CASCADE means unselecting a calendar, or
    # disconnecting the account above it, removes the events it brought in.
    calendar_id: Mapped[int | None] = mapped_column(
        ForeignKey("calendars.id", ondelete="CASCADE"), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    # Set when the user corrects how this event is classified — its type, prep
    # estimate or availability. Re-syncing must not overwrite a human decision
    # with a guess, so the importer leaves all three alone once this is set.
    type_locked: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="events")
    calendar: Mapped["Calendar | None"] = relationship(back_populates="events")
    periods: Mapped[list["Period"]] = relationship(
        secondary=period_events, back_populates="events")


class PeriodKind(str, enum.Enum):
    """What a generated block is for."""

    WORK = "work"
    # Time held clear for a meal. Serves no event, so it has no linked events.
    MEAL = "meal"


_PERIOD_KIND = Enum(PeriodKind, name="period_kind", native_enum=False,
                    create_constraint=True,
                    values_callable=lambda e: [m.value for m in e])


class Period(Base):
    """A generated block. Derived data: regeneration replaces these."""

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
    kind: Mapped[PeriodKind] = mapped_column(
        _PERIOD_KIND, default=PeriodKind.WORK,
        server_default=PeriodKind.WORK.value)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="periods")
    events: Mapped[list[Event]] = relationship(
        secondary=period_events, back_populates="periods")
