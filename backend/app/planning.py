"""The bridge between stored rows and the pure engine.

`app/core/scheduler.py` knows nothing about HTTP or the database: everything it
needs arrives as plain dataclasses. This module is what does the translating —
it loads rows, decides what each one means to the generator, calls it, and
writes the result back.

It sits between `api/` and `core/` deliberately. A router should be able to
answer a request without knowing how a Period becomes a PeriodPlan, and the
engine should never learn what a Session is. Both halves have their own tests
because both have their own failure modes.

Period *lifecycle* lives here too, not just generation: `apply_plan` writes and
replaces them, and `clear_orphaned_periods` removes the ones whose reason for
existing has gone away. Those belong together, and neither belongs in a router —
the importer and the events endpoint both need the cleanup.
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.scheduler import (
    BusyBlock,
    PeriodPlan,
    Prefs,
    SchedulePlan,
    Task,
    freeze_boundary,
    generate,
    is_locked,
)
from app.models import (
    Availability, Event, EventType, Period, PeriodKind, User, period_events,
)


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


# --- Mapping between ORM rows and the engine's plain dataclasses ---------

def user_prefs(user: User) -> Prefs:
    return Prefs(
        workdays=tuple(user.workdays),
        day_start=user.day_start,
        day_end=user.day_end,
        period_minutes=user.period_minutes,
        timezone=user.timezone,
    )


@dataclass(frozen=True)
class EngineInputs:
    """What the events in a window mean to the generator."""

    tasks: list[Task]
    busy: list[BusyBlock]
    windows: list[tuple[datetime, datetime]]
    # Meals the user placed themselves, which override the generated break.
    meals: list[tuple[datetime, datetime]]


def split_events(events: list[Event]) -> EngineInputs:
    """Sort events into work to do, time to avoid, and time to work in.

    Work windows are what makes a shift usable: not a wall to schedule around,
    but the part of the day when work actually happens, so periods go inside
    them. A meal both occupies its time and settles that day's break.
    """
    inputs = EngineInputs(tasks=[], busy=[], windows=[], meals=[])

    for event in events:
        if event.event_type == EventType.DEADLINE:
            inputs.tasks.append(Task(
                event_id=event.id,
                due_at=event.due_at,
                prep_minutes=event.expected_prep_minutes,
            ))
            continue

        if not event.starts_at or not event.ends_at:
            continue
        span = (event.starts_at, event.ends_at)

        if event.availability == Availability.BUSY:
            inputs.busy.append(BusyBlock(*span))
        elif event.availability == Availability.WORK_WINDOW:
            inputs.windows.append(span)
        elif event.availability == Availability.MEAL:
            # Occupies time like any commitment, and stands in for the break
            # the generator would otherwise reserve.
            inputs.busy.append(BusyBlock(*span))
            inputs.meals.append(span)
        # FREE events are informational: neither blocking nor offering time.

    return inputs


def load_events(db: Session, user: User, start: datetime, end: datetime) -> list[Event]:
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


def load_periods(db: Session, user: User, start: datetime, end: datetime) -> list[Period]:
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

    events = {e.id: e for e in load_events(db, user, start, end)}
    for planned in plan.new_periods:
        period = Period(
            user_id=user.id,
            starts_at=planned.starts_at,
            ends_at=planned.ends_at,
        )
        period.events = [events[i] for i in planned.event_ids if i in events]
        db.add(period)

    # Meals are written too, so the time reads as deliberately held rather
    # than as an unexplained gap in the day.
    for meal_start, meal_end in plan.meals:
        if meal_start >= now:
            db.add(Period(user_id=user.id, starts_at=meal_start,
                          ends_at=meal_end, kind=PeriodKind.MEAL))
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
    inputs = split_events(load_events(db, user, start, end))
    # A work window offers time the same way the user's own working hours do,
    # so it joins whatever extra availability the caller supplied.
    extra_windows = [*inputs.windows, *extra_windows]

    locked: list[PeriodPlan] = []
    if respect_horizon:
        boundary = freeze_boundary(
            now, user.schedule_horizon_days, ZoneInfo(user.timezone))
        locked = [as_period_plan(p) for p in load_periods(db, user, start, end)
                  if is_locked(as_period_plan(p), boundary)]

    return generate(
        inputs.tasks, inputs.busy, user_prefs(user), start, end, now,
        locked=locked, extra_windows=extra_windows,
        meal_minutes=user.lunch_minutes, existing_meals=inputs.meals,
    )


# --- Removing periods that no longer serve anything ----------------------

def clear_orphaned_periods(db: Session, user_id: int) -> int:
    """Delete work periods that no longer serve any event.

    Call this after anything that removes events — a deadline deleted by hand,
    a calendar unticked or disconnected, an event cancelled at the provider.

    Meal periods are deliberately exempt. They serve no event by design, so a
    blanket "period with no events" rule would delete every one of them.

    This ignores the commitment horizon on purpose: the freeze protects a plan
    the user can still act on, and there is nothing left to act on once the
    work is gone.
    """
    served = (
        select(period_events.c.period_id)
        .where(period_events.c.period_id == Period.id)
        .exists()
    )
    orphaned = list(db.scalars(
        select(Period.id).where(
            Period.user_id == user_id,
            Period.kind == PeriodKind.WORK,
            ~served,
        )
    ))
    if not orphaned:
        return 0

    db.execute(delete(Period).where(Period.id.in_(orphaned)))
    db.commit()
    return len(orphaned)
