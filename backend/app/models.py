"""
SQLAlchemy ORM models.
"""

from app.database import Base  # noqa: F401
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func, JSON
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
