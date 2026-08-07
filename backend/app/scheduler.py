"""Period allocation — the core of ScheduleAssist.

Pure logic: no FastAPI, no SQLAlchemy, and no clock. Everything the generator
needs arrives as an argument, including `now`, so the same inputs always
produce the same periods. That is what makes this unit-testable and what lets
`app/schedule.py` stay a thin load-call-save wrapper.

All datetimes crossing this boundary are UTC. The user's timezone matters in
exactly one place — deciding which instants count as "9am on a workday" — and
is applied per day so that a DST shift moves the workday with it.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# A deadline whose event carries no prep estimate still deserves a block of
# time; the model's NULL means "unknown", not "zero work". Inferred deadlines
# will frequently land here.
DEFAULT_PERIODS_PER_TASK = 1

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
    """One generated work block, ready to become a Period row."""

    starts_at: datetime
    ends_at: datetime
    event_ids: tuple[int, ...]


@dataclass(frozen=True)
class Unmet:
    """A task the window could not fully accommodate.

    Surfaced rather than swallowed so the UI can tell the user their week is
    overbooked instead of silently under-scheduling them.
    """

    event_id: int
    periods_needed: int
    periods_allocated: int
    reason: str


@dataclass(frozen=True)
class SchedulePlan:
    periods: tuple[PeriodPlan, ...]
    unmet: tuple[Unmet, ...]


def _as_utc(value: datetime) -> datetime:
    """Normalize to aware UTC. Naive input is assumed to already be UTC.

    Postgres hands back aware datetimes, but SQLite (tests) and hand-built
    fixtures do not, and comparing the two raises.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _merge_busy(busy: list[BusyBlock]) -> list[Interval]:
    """Sort and coalesce busy blocks so overlaps are subtracted only once."""
    intervals = sorted(
        (_as_utc(b.starts_at), _as_utc(b.ends_at)) for b in busy
    )
    merged: list[Interval] = []
    for start, end in intervals:
        if end <= start:
            continue  # Degenerate block; nothing to subtract.
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract_busy(window: Interval, merged: list[Interval]) -> list[Interval]:
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
) -> list[Interval]:
    """Every free, whole period in the window, earliest first.

    Slots never start in the past, never fall outside the user's workdays or
    working hours, and never overlap a busy block.
    """
    tz = ZoneInfo(prefs.timezone)
    # Nothing is schedulable in the past, so the window effectively opens now.
    floor = max(_as_utc(window_start), _as_utc(now))
    cap = _as_utc(window_end)
    if floor >= cap or prefs.period_minutes <= 0 or not prefs.workdays:
        return []

    merged = _merge_busy(busy)
    slots: list[Interval] = []

    # Walk local dates: a UTC day and a local workday are not the same span.
    day = floor.astimezone(tz).date()
    last_day = cap.astimezone(tz).date()
    while day <= last_day:
        if day.weekday() in prefs.workdays:
            start, end = _workday_bounds(day, prefs, tz)
            # Clip to the requested window and to the present.
            lo, hi = max(start, floor), min(end, cap)
            if lo < hi:
                for free in _subtract_busy((lo, hi), merged):
                    slots.extend(_chunk(free, prefs.period_minutes))
        day += timedelta(days=1)

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
) -> SchedulePlan:
    """Allocate work periods for `tasks` into the free time in the window.

    Earliest deadline first, and within a task the earliest slots that still
    finish before it is due. Front-loading is deliberate: the app exists for
    people who would otherwise leave the work until the night before, so given
    a choice between two valid slots it always picks the earlier one.

    Ties are broken by event id so the output is stable across runs.
    """
    slots = available_slots(prefs, busy, window_start, window_end, now)
    consumed = [False] * len(slots)
    floor = max(_as_utc(window_start), _as_utc(now))

    periods: list[PeriodPlan] = []
    unmet: list[Unmet] = []

    for task in sorted(tasks, key=lambda t: (_as_utc(t.due_at), t.event_id)):
        due = _as_utc(task.due_at)
        needed = _periods_needed(task, prefs.period_minutes)

        taken: list[int] = []
        if due > floor:
            for index, (start, end) in enumerate(slots):
                if len(taken) == needed:
                    break
                # A period only helps if the work finishes before it is due.
                if not consumed[index] and end <= due:
                    taken.append(index)

        for index in taken:
            consumed[index] = True
            start, end = slots[index]
            periods.append(PeriodPlan(start, end, (task.event_id,)))

        if len(taken) < needed:
            unmet.append(
                Unmet(
                    event_id=task.event_id,
                    periods_needed=needed,
                    periods_allocated=len(taken),
                    reason="overdue" if due <= floor else "no free time before deadline",
                )
            )

    periods.sort(key=lambda p: (p.starts_at, p.event_ids))
    return SchedulePlan(periods=tuple(periods), unmet=tuple(unmet))
