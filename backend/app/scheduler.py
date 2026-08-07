"""Period allocation — the core of ScheduleAssist.

Pure logic: no FastAPI, no SQLAlchemy, and no clock. Everything the generator
needs arrives as an argument, including `now`, so the same inputs always
produce the same periods. That is what makes this unit-testable and what lets
`app/schedule.py` stay a thin load-call-save wrapper.

All datetimes crossing this boundary are UTC. The user's timezone matters in
exactly one place — deciding which instants count as "9am on a workday" — and
is applied per day so that a DST shift moves the workday with it.

The engine never decides what to do about a shortfall. It reports one, and the
caller offers the user the choice: accept it, extend their hours, or rebuild
the whole schedule. Those three outcomes are all expressible as another call
with different arguments, which is why there is no "mode" parameter here.
"""

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

# A deadline whose event carries no prep estimate still deserves a block of
# time; the model's NULL means "unknown", not "zero work". Inferred deadlines
# will frequently land here.
DEFAULT_PERIODS_PER_TASK = 1

# --- Commitment horizon -------------------------------------------------
# How far ahead the schedule is treated as settled. Periods inside the horizon
# are not reshuffled when new events arrive, because a plan that rearranges
# itself the evening before is not a plan anyone can rely on.
DEFAULT_HORIZON_DAYS = 5  # A standard work week, counting today.
MIN_HORIZON_DAYS = 1
MAX_HORIZON_DAYS = 21

# Bounds worth warning about, but not forbidding.
SHORT_HORIZON_DAYS = 2
LONG_HORIZON_DAYS = 14

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class Prefs:
    """The scheduling knobs from the User row, decoupled from the ORM."""

    # ISO weekday numbers as `date.weekday()` produces them: Monday = 0.
    workdays: tuple[int, ...]
    day_start: time
    day_end: time
    period_minutes: int
    timezone: str


@dataclass(frozen=True)
class BusyBlock:
    """Committed time the generator must schedule around."""

    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class Task:
    """A deadline that needs prep time allocated before it."""

    event_id: int
    due_at: datetime
    # None means the user never estimated; see DEFAULT_PERIODS_PER_TASK.
    prep_minutes: int | None = None


@dataclass(frozen=True)
class PeriodPlan:
    """One work block, ready to become (or already backed by) a Period row.

    `period_id` is set only for periods that already exist in the database.
    Combined with `locked` it tells the caller what to write: locked periods
    are left alone, everything else is replaced.
    """

    starts_at: datetime
    ends_at: datetime
    event_ids: tuple[int, ...]
    period_id: int | None = None
    locked: bool = False


@dataclass(frozen=True)
class Unmet:
    """A task the window could not fully accommodate.

    Surfaced rather than swallowed so the caller can ask the user how to
    resolve it instead of silently under-scheduling them.
    """

    event_id: int
    periods_needed: int
    periods_allocated: int
    reason: str


@dataclass(frozen=True)
class SchedulePlan:
    """Every period that should exist in the window, locked ones included."""

    periods: tuple[PeriodPlan, ...]
    unmet: tuple[Unmet, ...]

    @property
    def new_periods(self) -> tuple[PeriodPlan, ...]:
        """The periods the caller needs to write; the rest already exist."""
        return tuple(p for p in self.periods if not p.locked)


def _as_utc(value: datetime) -> datetime:
    """Normalize to aware UTC. Naive input is assumed to already be UTC.

    Postgres hands back aware datetimes, but SQLite (tests) and hand-built
    fixtures do not, and comparing the two raises.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def horizon_warning(days: int) -> str | None:
    """Copy for a horizon at either extreme, or None when it is unremarkable."""
    if days <= SHORT_HORIZON_DAYS:
        return (
            "A short horizon means your schedule can be rearranged with very "
            "little notice, including work you planned to do tomorrow."
        )
    if days >= LONG_HORIZON_DAYS:
        return (
            "A long horizon means new deadlines will mostly be scheduled weeks "
            "out, because the time before then is already committed."
        )
    return None


def freeze_boundary(now: datetime, horizon_days: int, tz: ZoneInfo) -> datetime:
    """The first instant that is still open to rescheduling.

    The horizon counts today as day one and always lands on a local midnight,
    so the frozen edge moves once a day rather than creeping forward
    continuously — and can never fall in the middle of a period.
    """
    today = _as_utc(now).astimezone(tz).date()
    first_open_day = today + timedelta(days=horizon_days)
    return _as_utc(datetime.combine(first_open_day, time(0, 0), tzinfo=tz))


def is_locked(period: PeriodPlan, boundary: datetime) -> bool:
    """True when a period starts inside the frozen horizon."""
    return _as_utc(period.starts_at) < _as_utc(boundary)


def _union(intervals: Iterable[Interval]) -> list[Interval]:
    """Sort and coalesce intervals so overlaps are counted only once."""
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue  # Degenerate; nothing to contribute.
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(window: Interval, merged: list[Interval]) -> list[Interval]:
    """Return the parts of `window` left free by already-merged busy blocks."""
    lo, hi = window
    free: list[Interval] = []
    cursor = lo
    for start, end in merged:
        if end <= cursor:
            continue  # Entirely before the window.
        if start >= hi:
            break  # Merged blocks are sorted, so the rest are too late.
        if start > cursor:
            free.append((cursor, min(start, hi)))
        cursor = max(cursor, end)
        if cursor >= hi:
            return free
    if cursor < hi:
        free.append((cursor, hi))
    return free


def _chunk(interval: Interval, period_minutes: int) -> list[Interval]:
    """Cut a free interval into whole periods, discarding the remainder.

    A partial period is dropped rather than shortened: a 20-minute stub of a
    50-minute period is not a work session the user can do anything with.
    """
    lo, hi = interval
    length = timedelta(minutes=period_minutes)
    slots: list[Interval] = []
    cursor = lo
    while cursor + length <= hi:
        slots.append((cursor, cursor + length))
        cursor += length
    return slots


def _workday_bounds(day: date, prefs: Prefs, tz: ZoneInfo) -> Interval:
    """The user's working hours on a local date, as a UTC interval.

    Built per day on purpose. Anchoring once and adding 24h would drift by an
    hour across a DST boundary and silently schedule periods outside the
    user's stated hours.
    """
    start = datetime.combine(day, prefs.day_start, tzinfo=tz)
    end = datetime.combine(day, prefs.day_end, tzinfo=tz)
    return _as_utc(start), _as_utc(end)


def available_slots(
    prefs: Prefs,
    busy: list[BusyBlock],
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    extra_windows: Iterable[Interval] = (),
) -> list[Interval]:
    """Every free, whole period in the window, earliest first.

    Slots never start in the past and never overlap a busy block. They fall
    inside the user's workdays and working hours, plus any `extra_windows` the
    user explicitly opted into — that is the "work outside my usual hours"
    escape hatch, so those windows deliberately ignore workdays.
    """
    tz = ZoneInfo(prefs.timezone)
    # Nothing is schedulable in the past, so the window effectively opens now.
    floor = max(_as_utc(window_start), _as_utc(now))
    cap = _as_utc(window_end)
    if floor >= cap or prefs.period_minutes <= 0:
        return []

    candidates: list[Interval] = []
    if prefs.workdays:
        # Walk local dates: a UTC day and a local workday are not the same span.
        day = floor.astimezone(tz).date()
        last_day = cap.astimezone(tz).date()
        while day <= last_day:
            if day.weekday() in prefs.workdays:
                candidates.append(_workday_bounds(day, prefs, tz))
            day += timedelta(days=1)
    candidates.extend((_as_utc(s), _as_utc(e)) for s, e in extra_windows)

    # Union before chunking so that extended hours abutting a normal day form
    # one continuous run of periods instead of stranding a gap at the seam.
    unavailable = _union((_as_utc(b.starts_at), _as_utc(b.ends_at))
                         for b in busy)

    slots: list[Interval] = []
    for start, end in _union(candidates):
        lo, hi = max(start, floor), min(end, cap)
        if lo >= hi:
            continue
        for free in _subtract((lo, hi), unavailable):
            slots.extend(_chunk(free, prefs.period_minutes))

    slots.sort()
    return slots


def _periods_needed(task: Task, period_minutes: int) -> int:
    if task.prep_minutes is None:
        return DEFAULT_PERIODS_PER_TASK
    # Round up: 60 minutes of prep in 50-minute periods needs two, not one.
    return max(1, math.ceil(task.prep_minutes / period_minutes))


def generate(
    tasks: list[Task],
    busy: list[BusyBlock],
    prefs: Prefs,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
    locked: Iterable[PeriodPlan] = (),
    extra_windows: Iterable[Interval] = (),
) -> SchedulePlan:
    """Allocate work periods for `tasks` into the free time in the window.

    Earliest deadline first, and within a task the earliest slots that still
    finish before it is due. Front-loading is deliberate: the app exists for
    people who would otherwise leave the work until the night before, so given
    a choice between two valid slots it always picks the earlier one.

    `locked` periods are treated as immovable: they occupy their time like any
    other commitment, and they count toward their own task's allocation so it
    is not scheduled twice. Passing none is a full rebuild.

    Ties are broken by event id so the output is stable across runs.
    """
    # Normalize on the way in, not just for arithmetic: locked periods are
    # echoed straight into the result, and a naive one from the database would
    # otherwise make the final sort compare naive against aware.
    locked = tuple(
        replace(p, locked=True,
                starts_at=_as_utc(p.starts_at), ends_at=_as_utc(p.ends_at))
        for p in locked
    )

    # To the allocator an immovable period is indistinguishable from a meeting.
    occupied = list(busy) + [BusyBlock(p.starts_at, p.ends_at) for p in locked]
    slots = available_slots(prefs, occupied, window_start,
                            window_end, now, extra_windows)
    consumed = [False] * len(slots)
    floor = max(_as_utc(window_start), _as_utc(now))

    periods: list[PeriodPlan] = list(locked)
    unmet: list[Unmet] = []

    for task in sorted(tasks, key=lambda t: (_as_utc(t.due_at), t.event_id)):
        due = _as_utc(task.due_at)
        needed = _periods_needed(task, prefs.period_minutes)
        # Work already committed inside the horizon still counts as done.
        already = sum(1 for p in locked if task.event_id in p.event_ids)

        taken: list[int] = []
        if due > floor:
            for index, (_, end) in enumerate(slots):
                if len(taken) >= needed - already:
                    break
                # A period only helps if the work finishes before it is due.
                if not consumed[index] and end <= due:
                    taken.append(index)

        for index in taken:
            consumed[index] = True
            start, end = slots[index]
            periods.append(PeriodPlan(start, end, (task.event_id,)))

        allocated = already + len(taken)
        if allocated < needed:
            unmet.append(
                Unmet(
                    event_id=task.event_id,
                    periods_needed=needed,
                    periods_allocated=allocated,
                    reason="overdue" if due <= floor else "no free time before deadline",
                )
            )

    periods.sort(key=lambda p: (p.starts_at, p.event_ids))
    return SchedulePlan(periods=tuple(periods), unmet=tuple(unmet))
