"""
SQLAlchemy ORM models.
"""

from app.database import Base  # noqa: F401
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    identities: Mapped[list["AuthIdentity"]
                       ] = relationship(back_populates="user")


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))
    provider_subject: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str | None]

    user: Mapped[User] = relationship(back_populates="identities")
