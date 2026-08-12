"""Creating and editing events.

Two jobs. Manual events, for the things that live in nobody's calendar — the
assignment you were told about in class. And corrections to imported ones,
which is how a user tells the app that a title it guessed wrong is really a
deadline, or that their shift at work is time to schedule *into*.

Any correction sets `type_locked`, so the next sync updates the wording and
timing from the provider but leaves the user's judgement intact.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.database import get_db
from app.models import Availability, Event, EventSource, EventType, User
from app.planning import clear_orphaned_periods

router = APIRouter(prefix="/api/events", tags=["events"])


def event_json(event: Event) -> dict:
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "event_type": event.event_type.value,
        "source": event.source.value,
        "availability": event.availability.value,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "due_at": event.due_at,
        "is_all_day": event.is_all_day,
        "expected_prep_minutes": event.expected_prep_minutes,
        # True once the user has corrected the classification, so the UI can
        # show that a sync will no longer overwrite it.
        "type_locked": event.type_locked,
        "calendar_id": event.calendar_id,
    }


def _check_shape(
    event_type: EventType,
    starts_at: datetime | None,
    ends_at: datetime | None,
    due_at: datetime | None,
) -> None:
    """Mirror the database CHECK constraint with a readable 422.

    Without this the constraint still holds the line, but the user gets a
    500 and a stack trace instead of an explanation.
    """
    if event_type == EventType.DEADLINE:
        if due_at is None:
            raise HTTPException(
                status_code=422, detail="A deadline needs a due date")
        if starts_at or ends_at:
            raise HTTPException(
                status_code=422,
                detail="A deadline is a moment, so it cannot have a start or end")
    else:
        if starts_at is None or ends_at is None:
            raise HTTPException(
                status_code=422, detail="An event needs a start and an end")
        if ends_at <= starts_at:
            raise HTTPException(
                status_code=422, detail="An event must end after it starts")
        if due_at:
            raise HTTPException(
                status_code=422,
                detail="Only a deadline can have a due date")


class EventCreate(BaseModel):
    title: str
    description: str | None = None
    event_type: EventType = EventType.ONE_TIME
    availability: Availability = Availability.BUSY
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    due_at: datetime | None = None
    is_all_day: bool = False
    expected_prep_minutes: int | None = None

    @model_validator(mode="after")
    def _positive_prep(self):
        if self.expected_prep_minutes is not None and self.expected_prep_minutes <= 0:
            raise ValueError("expected_prep_minutes must be positive")
        return self


class EventUpdate(BaseModel):
    """Every field optional; only what is sent is changed.

    `event_type` can be flipped, which is the main point of this endpoint —
    turning a misread calendar entry into a real deadline. Doing so requires
    sending the times that match the new shape.
    """

    title: str | None = None
    description: str | None = None
    event_type: EventType | None = None
    availability: Availability | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    due_at: datetime | None = None
    expected_prep_minutes: int | None = None
    # Lets a user hand an event back to inference after correcting it.
    type_locked: bool | None = None

    @model_validator(mode="after")
    def _positive_prep(self):
        if self.expected_prep_minutes is not None and self.expected_prep_minutes <= 0:
            raise ValueError("expected_prep_minutes must be positive")
        return self


def _owned(event_id: int, user: User, db: Session) -> Event:
    event = db.scalar(
        select(Event).where(Event.id == event_id, Event.user_id == user.id))
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", status_code=201)
def create_event(
    payload: EventCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add an event by hand. Deadlines created here drive generation."""
    _check_shape(payload.event_type, payload.starts_at,
                 payload.ends_at, payload.due_at)

    event = Event(
        user_id=user.id,
        source=EventSource.MANUAL,
        title=payload.title,
        description=payload.description,
        event_type=payload.event_type,
        availability=payload.availability,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        due_at=payload.due_at,
        is_all_day=payload.is_all_day,
        expected_prep_minutes=payload.expected_prep_minutes,
        # Nothing guessed it, so there is nothing for a sync to overwrite.
        type_locked=True,
    )
    db.add(event)
    db.commit()
    return event_json(event)


@router.get("/{event_id}")
def get_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return event_json(_owned(event_id, user, db))


@router.patch("/{event_id}")
def update_event(
    event_id: int,
    payload: EventUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Correct an event's details or how the generator should read it."""
    event = _owned(event_id, user, db)
    fields = payload.model_dump(exclude_unset=True)

    event_type = fields.get("event_type", event.event_type)
    # Times default to the event's current values, except when the type is
    # changing: the old shape's columns cannot survive the switch.
    changing_type = event_type != event.event_type
    starts_at = fields.get(
        "starts_at", None if changing_type else event.starts_at)
    ends_at = fields.get("ends_at", None if changing_type else event.ends_at)
    due_at = fields.get("due_at", None if changing_type else event.due_at)

    _check_shape(event_type, starts_at, ends_at, due_at)

    event.event_type = event_type
    event.starts_at = starts_at
    event.ends_at = ends_at
    event.due_at = due_at

    for field in ("title", "description", "availability",
                  "expected_prep_minutes"):
        if field in fields:
            setattr(event, field, fields[field])

    # Any change to how this event is read is a decision a sync must respect,
    # unless the user is explicitly handing it back to inference.
    if "type_locked" in fields:
        event.type_locked = fields["type_locked"]
    elif {"event_type", "availability", "expected_prep_minutes"} & fields.keys():
        event.type_locked = True

    db.commit()
    return event_json(event)


@router.delete("/{event_id}", status_code=204)
def delete_event(
    event_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove an event the user created, and any periods left serving nothing.

    Imported events are not deletable: the next sync would bring them straight
    back. Marking one as free, or unticking its calendar, is the way to get it
    out of the schedule.

    Deleting a deadline clears the periods allocated for it. Those blocks only
    ever meant "work toward this", so leaving them would hold time for work the
    user has just said they no longer have. A period shared with another
    deadline survives, because that other work still needs it.
    """
    event = _owned(event_id, user, db)
    if event.source == EventSource.IMPORTED:
        raise HTTPException(
            status_code=409,
            detail="Imported events come back on the next sync. "
                   "Mark it as free instead, or untick its calendar.",
        )
    db.delete(event)
    db.commit()
    clear_orphaned_periods(db, user.id)
