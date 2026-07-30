"""
SQLAlchemy ORM models.
"""

from app.crypto import EncryptedString
from app.database import Base  # noqa: F401
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship


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

    workday_preferences: Mapped[dict] = mapped_column(
        # Default workday preferences
        JSON, default=lambda: {"monday": "9:00-17:00", "tuesday": "9:00-17:00", "wednesday": "9:00-17:00", "thursday": "9:00-17:00", "friday": "9:00-17:00"})


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
