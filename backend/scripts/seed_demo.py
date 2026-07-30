"""Populate a user's current week with demo events and periods.

Until the import (#8) and generation (#10) paths exist, this is how you get a
schedule worth looking at. Safe to re-run: it clears the demo rows it created
before inserting fresh ones.

    PYTHONPATH=. .venv/bin/python scripts/seed_demo.py you@example.com
"""

import sys
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Event, EventSource, EventType, Period, User

DEMO_MARKER = "[demo]"


def at(day: datetime, hh: int, mm: int = 0) -> datetime:
    return day.replace(hour=hh, minute=mm, second=0, microsecond=0)


def main(email: str) -> int:
    db = SessionLocal()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        existing = db.scalars(select(User.email)).all()
        print(f"No user {email!r}. Known users: {existing or '(none)'}")
        db.close()
        return 1

    # Clear anything a previous run left behind.
    for period in db.scalars(select(Period).where(Period.user_id == user.id)).all():
        db.delete(period)
    for event in db.scalars(
        select(Event).where(Event.user_id == user.id,
                            Event.description.like(f"{DEMO_MARKER}%"))
    ).all():
        db.delete(event)
    db.commit()

    # Monday of the current week, in the user's local wall clock.
    today = datetime.now(timezone.utc)
    monday = at(today - timedelta(days=today.weekday()), 0)

    def d(offset: int) -> datetime:
        return monday + timedelta(days=offset)

    events = [
        Event(user_id=user.id, title="CS406 Lecture", description=f"{DEMO_MARKER} imported",
              event_type=EventType.ONE_TIME, source=EventSource.IMPORTED,
              starts_at=at(d(0), 10), ends_at=at(d(0), 11, 30)),
        Event(user_id=user.id, title="CS406 Lecture", description=f"{DEMO_MARKER} imported",
              event_type=EventType.ONE_TIME, source=EventSource.IMPORTED,
              starts_at=at(d(2), 10), ends_at=at(d(2), 11, 30)),
        Event(user_id=user.id, title="Standup", description=f"{DEMO_MARKER} imported",
              event_type=EventType.ONE_TIME, source=EventSource.IMPORTED,
              starts_at=at(d(1), 9, 30), ends_at=at(d(1), 10)),
        Event(user_id=user.id, title="Advising appointment",
              description=f"{DEMO_MARKER} overlaps the lecture on purpose",
              event_type=EventType.ONE_TIME, source=EventSource.IMPORTED,
              starts_at=at(d(2), 11), ends_at=at(d(2), 12)),
        Event(user_id=user.id, title="Study group", description=f"{DEMO_MARKER} manual",
              event_type=EventType.ONE_TIME, source=EventSource.MANUAL,
              starts_at=at(d(3), 14), ends_at=at(d(3), 16)),
        Event(user_id=user.id, title="Dentist", description=f"{DEMO_MARKER} manual",
              event_type=EventType.ONE_TIME, source=EventSource.MANUAL,
              starts_at=at(d(4), 9), ends_at=at(d(4), 10)),
        Event(user_id=user.id, title="Reading day", description=f"{DEMO_MARKER} all day",
              event_type=EventType.ONE_TIME, source=EventSource.IMPORTED,
              starts_at=at(d(5), 0), ends_at=at(d(5), 23, 59), is_all_day=True),
    ]
    deadlines = [
        Event(user_id=user.id, title="Project milestone 3",
              description=f"{DEMO_MARKER} deadline", event_type=EventType.DEADLINE,
              source=EventSource.MANUAL, due_at=at(d(3), 23, 59),
              expected_prep_minutes=300),
        Event(user_id=user.id, title="Reading response",
              description=f"{DEMO_MARKER} deadline", event_type=EventType.DEADLINE,
              source=EventSource.IMPORTED, due_at=at(d(1), 17),
              expected_prep_minutes=90),
    ]
    db.add_all(events + deadlines)
    db.commit()

    milestone, reading = deadlines
    # Stand-ins for what the generator (#10) will produce.
    periods = [
        (at(d(0), 13), at(d(0), 14, 40), [milestone]),
        (at(d(1), 13), at(d(1), 13, 50), [reading]),
        (at(d(2), 13), at(d(2), 14, 40), [milestone]),
        (at(d(2), 15), at(d(2), 15, 50), [milestone, reading]),  # serves two
        (at(d(3), 9), at(d(3), 10, 40), [milestone]),
    ]
    for starts_at, ends_at, served in periods:
        db.add(Period(user_id=user.id, starts_at=starts_at,
                      ends_at=ends_at, events=served))
    db.commit()

    print(f"Seeded {len(events) + len(deadlines)} events and {len(periods)} periods "
          f"for {email} (week of {monday.date()})")
    db.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
