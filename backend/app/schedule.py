"""Read-only schedule feed for the calendar view.

Issue #11 owns the schedule API as a whole; this is the fetch half, which the
week view needs before it can render anything. Generate/regenerate arrives with
the engine (#10) and belongs in this router too.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Event, Period, User

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

# Guards against a client asking for a decade of data in one request.
MAX_RANGE = timedelta(days=62)


def _event_json(event: Event) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "event_type": event.event_type.value,
        "source": event.source.value,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "due_at": event.due_at,
        "is_all_day": event.is_all_day,
        "expected_prep_minutes": event.expected_prep_minutes,
    }


def _period_json(period: Period) -> dict:
    return {
        "id": period.id,
        "starts_at": period.starts_at,
        "ends_at": period.ends_at,
        # The events this block was generated to serve, for labelling.
        "events": [{"id": e.id, "title": e.title} for e in period.events],
    }


@router.get("")
def get_schedule(
    start: datetime,
    end: datetime,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Everything that should appear on the calendar between start and end."""
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if end - start > MAX_RANGE:
        raise HTTPException(
            status_code=422, detail=f"range must be at most {MAX_RANGE.days} days")

    events = db.scalars(
        select(Event)
        .where(
            Event.user_id == user.id,
            or_(
                # Timed events overlapping the window, not merely starting in it.
                and_(Event.starts_at < end, Event.ends_at > start),
                and_(Event.due_at >= start, Event.due_at < end),
            ),
        )
        .order_by(Event.starts_at, Event.due_at)
    ).all()

    periods = db.scalars(
        select(Period)
        .options(selectinload(Period.events))
        .where(
            Period.user_id == user.id,
            Period.starts_at < end,
            Period.ends_at > start,
        )
        .order_by(Period.starts_at)
    ).all()

    return {
        "start": start,
        "end": end,
        # The grid needs the user's working hours to know what to draw.
        "preferences": {
            "workdays": user.workdays,
            "day_start": user.day_start,
            "day_end": user.day_end,
            "period_minutes": user.period_minutes,
            "timezone": user.timezone,
        },
        "events": [_event_json(e) for e in events],
        "periods": [_period_json(p) for p in periods],
    }
