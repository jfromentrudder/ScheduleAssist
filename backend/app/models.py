"""SQLAlchemy ORM models.

Add your models here, e.g.:

    from sqlalchemy.orm import Mapped, mapped_column
    from app.database import Base

    class Event(Base):
        __tablename__ = "events"

        id: Mapped[int] = mapped_column(primary_key=True)
        title: Mapped[str]
"""

from app.database import Base  # noqa: F401
