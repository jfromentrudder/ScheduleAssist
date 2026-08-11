"""Schedule API: read the calendar feed, and generate the periods on it.

The generator itself lives in `app/scheduler.py` and knows nothing about HTTP
or the database. This module is the adapter: it loads rows, hands plain
dataclasses to the engine, and writes the result back.

Generation deliberately does not resolve its own shortfalls. When the schedule
cannot absorb a new deadline, the endpoint reports what fell short and which
remedies would actually work, and the user chooses. See `generate_schedule`.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, selectinload
from zoneinfo import ZoneInfo

from app.auth import get_current_user
from app.database import get_db
from app.models import Availability, Event, EventType, Period, User
from app.scheduler import (
    BusyBlock,
    PeriodPlan,
    Prefs,
    SchedulePlan,
    Task,
    freeze_boundary,
    generate,
    is_locked,
)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

# Guards against a client asking for a decade of data in one request.
MAX_RANGE = timedelta(days=62)

# How far ahead generation looks by default. Bounded on purpose: the engine
# front-loads work, so an unbounded window would spend this afternoon on a
# deadline three months out.
PLANNING_WINDOW = timedelta(days=28)


def _event_json(event: Event) -> dict:
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
        "type_locked": event.type_locked,
    }


def shapes_the_day(event: Event) -> bool:
    """Whether an event belongs in the generated view.

    That view answers "what am I doing today", so it carries the things that
    constrain the answer: deadlines being worked toward, commitments that take
    real time, and the windows work happens in. What it leaves out is the
    informational clutter — the all-day markers and reminders that would
    otherwise bury the schedule the app exists to produce.
    """
    if event.event_type == EventType.DEADLINE:
        return True
    return event.availability in (Availability.BUSY, Availability.WORK_WINDOW)


def _period_json(period: Period, boundary: datetime) -> dict:
    return {
        "id": period.id,
        "starts_at": period.starts_at,
        "ends_at": period.ends_at,
        # Locked is derived from the horizon, not stored: it is a fact about
        # when the client is looking, not about the row.
        "locked": is_locked(
            PeriodPlan(period.starts_at, period.ends_at, ()), boundary),
        # The events this block was generated to serve, for labelling.
        "events": [{"id": e.id, "title": e.title} for e in period.events],
    }


# --- Mapping between ORM rows and the engine's plain dataclasses ---------

def user_prefs(user: User) -> Prefs:
    return Prefs(
        workdays=tuple(user.workdays),
        day_start=user.day_start,
        day_end=user.day_end,
        period_minutes=user.period_minutes,
        timezone=user.timezone,
    )


def split_events(
    events: list[Event],
) -> tuple[list[Task], list[BusyBlock], list[tuple[datetime, datetime]]]:
    """Sort events into work to do, time to avoid, and time to work in.

    The third category is what makes a shift at work usable: it is not a wall
    to schedule around, it is the part of the day when work actually happens,
    so the generator places periods inside it.
    """
    tasks: list[Task] = []
    busy: list[BusyBlock] = []
    windows: list[tuple[datetime, datetime]] = []

    for event in events:
        if event.event_type == EventType.DEADLINE:
            tasks.append(Task(
                event_id=event.id,
                due_at=event.due_at,
                prep_minutes=event.expected_prep_minutes,
            ))
            continue

        if not event.starts_at or not event.ends_at:
            continue
        if event.availability == Availability.BUSY:
            busy.append(BusyBlock(event.starts_at, event.ends_at))
        elif event.availability == Availability.WORK_WINDOW:
            windows.append((event.starts_at, event.ends_at))
        # FREE events are informational: neither blocking nor offering time.

    return tasks, busy, windows


def _load_events(db: Session, user: User, start: datetime, end: datetime) -> list[Event]:
    return list(db.scalars(
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
    ))


def _load_periods(db: Session, user: User, start: datetime, end: datetime) -> list[Period]:
    return list(db.scalars(
        select(Period)
        .options(selectinload(Period.events))
        .where(
            Period.user_id == user.id,
            Period.starts_at < end,
            Period.ends_at > start,
        )
        .order_by(Period.starts_at)
    ))


def as_period_plan(period: Period) -> PeriodPlan:
    return PeriodPlan(
        starts_at=period.starts_at,
        ends_at=period.ends_at,
        event_ids=tuple(sorted(e.id for e in period.events)),
        period_id=period.id,
    )


def apply_plan(
    db: Session,
    user: User,
    plan: SchedulePlan,
    start: datetime,
    end: datetime,
    now: datetime,
) -> None:
    """Replace the user's unlocked periods in the window with the plan's.

    Locked rows are matched by id and left untouched. Anything already under
    way is left alone too: rewriting a period the user is sitting in the middle
    of is never the right answer.
    """
    keep = {p.period_id for p in plan.periods if p.locked and p.period_id}

    stale = select(Period.id).where(
        Period.user_id == user.id,
        Period.starts_at < end,
        Period.ends_at > start,
        Period.starts_at >= now,
    )
    if keep:
        stale = stale.where(Period.id.notin_(keep))
    doomed = list(db.scalars(stale))
    if doomed:
        db.execute(delete(Period).where(Period.id.in_(doomed)))

    events = {e.id: e for e in _load_events(db, user, start, end)}
    for planned in plan.new_periods:
        period = Period(
            user_id=user.id,
            starts_at=planned.starts_at,
            ends_at=planned.ends_at,
        )
        period.events = [events[i] for i in planned.event_ids if i in events]
        db.add(period)
    db.commit()


def build_plan(
    db: Session,
    user: User,
    start: datetime,
    end: datetime,
    now: datetime,
    respect_horizon: bool,
    extra_windows: list[tuple[datetime, datetime]] = (),
) -> SchedulePlan:
    """Run the engine over the user's current rows without writing anything."""
    tasks, busy, windows = split_events(_load_events(db, user, start, end))
    # A work window offers time the same way the user's own working hours do,
    # so it joins whatever extra availability the caller supplied.
    extra_windows = [*windows, *extra_windows]

    locked: list[PeriodPlan] = []
    if respect_horizon:
        boundary = freeze_boundary(
            now, user.schedule_horizon_days, ZoneInfo(user.timezone))
        locked = [as_period_plan(p) for p in _load_periods(db, user, start, end)
                  if is_locked(as_period_plan(p), boundary)]

    return generate(
        tasks, busy, user_prefs(user), start, end, now,
        locked=locked, extra_windows=extra_windows,
    )


# --- Endpoints ----------------------------------------------------------

@router.get("")
def get_schedule(
    start: datetime,
    end: datetime,
    view: Literal["generated", "calendar"] = "generated",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Everything that should appear on the calendar between start and end.

    Two views over the same data, deliberately not duplicates of each other.
    "generated" is the app's own output — the periods it allocated, the
    deadlines they serve, and the commitments they had to work around.
    "calendar" is the diary as the user wrote it: every entry, and no periods,
    because generated blocks are not something they put there.

    Commitments are the one thing both views carry, since a meeting matters
    whichever question you are asking.
    """
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if end - start > MAX_RANGE:
        raise HTTPException(
            status_code=422, detail=f"range must be at most {MAX_RANGE.days} days")

    now = datetime.now(timezone.utc)
    boundary = freeze_boundary(
        now, user.schedule_horizon_days, ZoneInfo(user.timezone))

    events = _load_events(db, user, start, end)
    generated = view == "generated"
    if generated:
        events = [e for e in events if shapes_the_day(e)]

    # Periods belong to the generated view alone. Showing them alongside the
    # raw diary would read as duplicates of the schedule rather than as the
    # separate thing they are.
    periods = _load_periods(db, user, start, end) if generated else []

    return {
        "start": start,
        "end": end,
        "view": view,
        # The grid needs the user's working hours to know what to draw.
        "preferences": {
            "workdays": user.workdays,
            "day_start": user.day_start,
            "day_end": user.day_end,
            "period_minutes": user.period_minutes,
            "timezone": user.timezone,
            "schedule_horizon_days": user.schedule_horizon_days,
        },
        # Where the settled part of the schedule ends, so the view can mark it.
        # Meaningless without periods, so only the generated view draws it.
        "horizon_ends_at": boundary if generated else None,
        "events": [_event_json(e) for e in events],
        "periods": [_period_json(p, boundary) for p in periods],
    }


class ExtraWindow(BaseModel):
    starts_at: datetime
    ends_at: datetime


class GenerateRequest(BaseModel):
    """Options mirror the choices the UI offers when a deadline will not fit."""

    # "additive" keeps everything inside the horizon exactly where it is.
    # "rebuild" is the user explicitly accepting that their week will change.
    strategy: Literal["additive", "rebuild"] = "additive"
    # Availability outside normal working hours, when the user opts into it.
    extra_windows: list[ExtraWindow] = []
    # Commit even though some work could not be placed.
    accept_unmet: bool = False
    start: datetime | None = None
    end: datetime | None = None


def _unmet_json(plan: SchedulePlan) -> list[dict]:
    return [
        {
            "event_id": u.event_id,
            "periods_needed": u.periods_needed,
            "periods_allocated": u.periods_allocated,
            "reason": u.reason,
        }
        for u in plan.unmet
    ]


@router.post("/generate")
def generate_schedule(
    request: GenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate or regenerate periods, and report anything that would not fit.

    The default pass is additive: work already committed inside the horizon
    stays put, and new deadlines take whatever gaps are left. If that leaves a
    deadline short, nothing is written — the response instead describes the
    shortfall and which remedies would resolve it, and the client calls back
    with the user's choice.
    """
    now = datetime.now(timezone.utc)
    start = request.start or now
    end = request.end or (start + PLANNING_WINDOW)
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    if end - start > MAX_RANGE:
        raise HTTPException(
            status_code=422, detail=f"range must be at most {MAX_RANGE.days} days")

    extra = [(w.starts_at, w.ends_at) for w in request.extra_windows]
    for window_start, window_end in extra:
        if window_end <= window_start:
            raise HTTPException(
                status_code=422, detail="extra window must end after it starts")

    respect_horizon = request.strategy == "additive"
    plan = build_plan(db, user, start, end, now, respect_horizon, extra)

    # A shortfall the user has not yet seen is a question, not a result. The
    # exception is a rebuild or an extended-hours pass: those *are* the answer
    # to that question, so committing them is what the user just asked for.
    needs_a_decision = (
        plan.unmet
        and not request.accept_unmet
        and respect_horizon
        and not extra
    )
    if needs_a_decision:
        # Only offer a rebuild if it would actually help; otherwise the user is
        # being asked to blow up their week for nothing.
        rebuilt = build_plan(db, user, start, end, now, respect_horizon=False)
        return {
            "committed": False,
            "unmet": _unmet_json(plan),
            "options": {
                "rebuild": {
                    "resolves": len(rebuilt.unmet) < len(plan.unmet),
                    "periods_moved": len(rebuilt.new_periods),
                },
                "extend_hours": {"available": True},
                "accept_unmet": {"available": True},
            },
        }

    apply_plan(db, user, plan, start, end, now)
    return {
        "committed": True,
        "start": start,
        "end": end,
        "periods_created": len(plan.new_periods),
        "periods_kept": len(plan.periods) - len(plan.new_periods),
        "unmet": _unmet_json(plan),
    }
