"""Tests for the commitment horizon: locked periods, extended hours, and the
frozen edge.

The rule these all serve: a schedule the user has already seen inside their
horizon does not rearrange itself underneath them.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.scheduler import (
    BusyBlock,
    PeriodPlan,
    Prefs,
    Task,
    available_slots,
    freeze_boundary,
    generate,
    horizon_warning,
    is_locked,
    DEFAULT_HORIZON_DAYS,
    MAX_HORIZON_DAYS,
    MIN_HORIZON_DAYS,
)

MONDAY = datetime(2026, 8, 10, tzinfo=timezone.utc)
WEEK_END = MONDAY + timedelta(days=7)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def prefs() -> Prefs:
    """9-5 UTC, Mon-Fri, 60-minute periods: eight slots a day."""
    return Prefs(
        workdays=(0, 1, 2, 3, 4),
        day_start=time(9, 0),
        day_end=time(17, 0),
        period_minutes=60,
        timezone="UTC",
    )


# --- The frozen edge ----------------------------------------------------

def test_horizon_counts_today_as_day_one():
    """5 days means Mon-Fri when it is Monday, not Mon through Saturday."""
    boundary = freeze_boundary(utc(2026, 8, 10, 14, 30), 5, ZoneInfo("UTC"))
    assert boundary == utc(2026, 8, 15)  # Saturday 00:00 is the first open slot


def test_minimum_horizon_freezes_only_today():
    boundary = freeze_boundary(utc(2026, 8, 10, 14, 30), 1, ZoneInfo("UTC"))
    assert boundary == utc(2026, 8, 11)


def test_boundary_lands_on_local_midnight_not_the_current_time():
    """The edge must not bisect a period, so it never tracks the clock."""
    morning = freeze_boundary(utc(2026, 8, 10, 6, 0), 5, ZoneInfo("UTC"))
    evening = freeze_boundary(utc(2026, 8, 10, 23, 0), 5, ZoneInfo("UTC"))
    assert morning == evening


def test_boundary_follows_the_users_timezone():
    """Midnight in Los Angeles is 07:00 UTC, not 00:00 UTC."""
    boundary = freeze_boundary(utc(2026, 8, 10, 14, 30), 1,
                               ZoneInfo("America/Los_Angeles"))
    assert boundary == utc(2026, 8, 11, 7)


def test_is_locked_splits_periods_at_the_boundary():
    boundary = utc(2026, 8, 15)
    inside = PeriodPlan(utc(2026, 8, 14, 9), utc(2026, 8, 14, 10), (1,))
    outside = PeriodPlan(utc(2026, 8, 17, 9), utc(2026, 8, 17, 10), (1,))

    assert is_locked(inside, boundary)
    assert not is_locked(outside, boundary)


# --- Warnings at the extremes -------------------------------------------

def test_default_horizon_is_unremarkable():
    assert horizon_warning(DEFAULT_HORIZON_DAYS) is None


@pytest.mark.parametrize("days", [MIN_HORIZON_DAYS, 2, 14, MAX_HORIZON_DAYS])
def test_extreme_horizons_warn(days):
    """Asserting a warning exists, not its wording — the copy will be edited."""
    assert horizon_warning(days)


def test_the_two_extremes_warn_about_different_things():
    assert horizon_warning(MIN_HORIZON_DAYS) != horizon_warning(MAX_HORIZON_DAYS)


# --- Locked periods -----------------------------------------------------

def test_locked_periods_are_preserved_and_marked(prefs):
    locked = [PeriodPlan(utc(2026, 8, 10, 9), utc(2026, 8, 10, 10),
                         (1,), period_id=99)]
    plan = generate([], [], prefs, MONDAY, WEEK_END, now=MONDAY, locked=locked)

    assert len(plan.periods) == 1
    assert plan.periods[0].period_id == 99
    assert plan.periods[0].locked is True
    # Nothing new to write: the caller should leave the existing row alone.
    assert plan.new_periods == ()


def test_new_work_never_overlaps_a_locked_period(prefs):
    locked = [PeriodPlan(utc(2026, 8, 10, 9), utc(2026, 8, 10, 10), (1,))]
    task = Task(event_id=2, due_at=utc(2026, 8, 10, 17), prep_minutes=60)

    plan = generate([task], [], prefs, MONDAY, WEEK_END,
                    now=MONDAY, locked=locked)

    fresh = plan.new_periods
    assert len(fresh) == 1
    assert fresh[0].starts_at == utc(2026, 8, 10, 10)


def test_locked_periods_count_toward_their_own_task(prefs):
    """Two hours already committed plus two more, not four more."""
    task = Task(event_id=1, due_at=utc(2026, 8, 14, 17), prep_minutes=240)
    locked = [
        PeriodPlan(utc(2026, 8, 10, 9), utc(2026, 8, 10, 10), (1,)),
        PeriodPlan(utc(2026, 8, 10, 10), utc(2026, 8, 10, 11), (1,)),
    ]

    plan = generate([task], [], prefs, MONDAY, WEEK_END,
                    now=MONDAY, locked=locked)

    assert len(plan.new_periods) == 2
    assert len(plan.periods) == 4
    assert plan.unmet == ()


def test_fully_satisfied_locked_task_gets_nothing_new(prefs):
    task = Task(event_id=1, due_at=utc(2026, 8, 14, 17), prep_minutes=60)
    locked = [PeriodPlan(utc(2026, 8, 10, 9), utc(2026, 8, 10, 10), (1,))]

    plan = generate([task], [], prefs, MONDAY, WEEK_END,
                    now=MONDAY, locked=locked)

    assert plan.new_periods == ()
    assert plan.unmet == ()


def test_urgent_task_takes_free_slots_inside_the_frozen_zone(prefs):
    """The additive case: a late deadline uses gaps without moving anything."""
    # Monday morning is committed to task 1; the afternoon is still empty.
    locked = [
        PeriodPlan(utc(2026, 8, 10, h), utc(2026, 8, 10, h + 1), (1,))
        for h in range(9, 13)
    ]
    urgent = Task(event_id=2, due_at=utc(2026, 8, 10, 17), prep_minutes=120)

    plan = generate([urgent], [], prefs, MONDAY, WEEK_END,
                    now=MONDAY, locked=locked)

    fresh = plan.new_periods
    assert len(fresh) == 2
    # Second period starts after the buffer, not straight after the first.
    assert [p.starts_at for p in fresh] == [
        utc(2026, 8, 10, 13), utc(2026, 8, 10, 14, 10)]
    # The committed morning is untouched.
    assert all(p.locked for p in plan.periods if p.event_ids == (1,))


def test_additive_shortfall_is_reported_for_the_user_to_resolve(prefs):
    """When the free gaps are not enough, the caller needs to know by how much
    so it can offer the rebuild / extend-hours / accept choice."""
    # The whole of Monday is already committed to task 1.
    locked = [
        PeriodPlan(utc(2026, 8, 10, h), utc(2026, 8, 10, h + 1), (1,))
        for h in range(9, 17)
    ]
    urgent = Task(event_id=2, due_at=utc(2026, 8, 10, 17), prep_minutes=120)

    plan = generate([urgent], [], prefs, MONDAY, WEEK_END,
                    now=MONDAY, locked=locked)

    assert plan.new_periods == ()
    assert plan.unmet[0].event_id == 2
    assert plan.unmet[0].periods_needed == 2
    assert plan.unmet[0].periods_allocated == 0


def test_full_rebuild_can_satisfy_what_additive_could_not(prefs):
    """Dropping `locked` is the whole of the 'regenerate everything' option."""
    tasks = [
        Task(event_id=1, due_at=utc(2026, 8, 14, 17), prep_minutes=480),
        Task(event_id=2, due_at=utc(2026, 8, 10, 17), prep_minutes=120),
    ]
    locked = [
        PeriodPlan(utc(2026, 8, 10, h), utc(2026, 8, 10, h + 1), (1,))
        for h in range(9, 17)
    ]

    additive = generate(tasks, [], prefs, MONDAY, WEEK_END,
                        now=MONDAY, locked=locked)
    rebuilt = generate(tasks, [], prefs, MONDAY, WEEK_END, now=MONDAY)

    assert additive.unmet  # Task 2 cannot fit around the committed Monday.
    assert rebuilt.unmet == ()  # Reshuffling frees Monday for the urgent one.
    assert all(p.event_ids == (2,) for p in rebuilt.periods[:2])


# --- Extended hours -----------------------------------------------------

def test_extra_windows_open_time_outside_working_hours(prefs):
    evening = (utc(2026, 8, 10, 18), utc(2026, 8, 10, 21))
    slots = available_slots(prefs, [], MONDAY, MONDAY + timedelta(days=1),
                            now=MONDAY, extra_windows=[evening])

    assert len(slots) == 9  # Seven in normal hours, two in the evening.
    assert slots[-1] == (utc(2026, 8, 10, 19, 10), utc(2026, 8, 10, 20, 10))


def test_extra_windows_ignore_workdays(prefs):
    """Weekend availability is the point of the escape hatch."""
    saturday = (utc(2026, 8, 15, 10), utc(2026, 8, 15, 13))
    slots = available_slots(prefs, [], utc(2026, 8, 15), utc(2026, 8, 16),
                            now=utc(2026, 8, 15), extra_windows=[saturday])

    assert len(slots) == 2
    assert all(start.weekday() == 5 for start, _ in slots)


def test_extended_hours_abutting_the_workday_form_one_run():
    """Unioned before chunking, so the seam does not strand a partial period."""
    # 50-minute periods on a 7.5-hour day: seven fit, and the last 40 minutes
    # are too short for an eighth once the buffer is counted.
    fifty = Prefs(workdays=(0,), day_start=time(9, 0), day_end=time(16, 30),
                  period_minutes=50, timezone="UTC")

    normal = available_slots(fifty, [], MONDAY, MONDAY + timedelta(days=1),
                             now=MONDAY)
    extended = available_slots(fifty, [], MONDAY, MONDAY + timedelta(days=1),
                               now=MONDAY,
                               extra_windows=[(utc(2026, 8, 10, 16, 30),
                                               utc(2026, 8, 10, 19))])

    # Chunking the two spans separately would strand that 40-minute stub and
    # yield nine; unioning them first recovers it for a tenth period.
    assert len(normal) == 7
    assert len(extended) == 10


def test_extra_windows_still_respect_busy_time(prefs):
    dinner = BusyBlock(utc(2026, 8, 10, 18), utc(2026, 8, 10, 19))
    slots = available_slots(prefs, [dinner], MONDAY, MONDAY + timedelta(days=1),
                            now=MONDAY,
                            extra_windows=[(utc(2026, 8, 10, 18),
                                            utc(2026, 8, 10, 21))])

    evening = [s for s in slots if s[0].hour >= 18]
    assert evening == [(utc(2026, 8, 10, 19), utc(2026, 8, 10, 20))]


def test_extending_hours_resolves_an_otherwise_unmet_task(prefs):
    """The third option offered to the user, end to end."""
    locked = [
        PeriodPlan(utc(2026, 8, 10, h), utc(2026, 8, 10, h + 1), (1,))
        for h in range(9, 17)
    ]
    urgent = Task(event_id=2, due_at=utc(2026, 8, 10, 21), prep_minutes=120)

    before = generate([urgent], [], prefs, MONDAY, WEEK_END,
                      now=MONDAY, locked=locked)
    after = generate([urgent], [], prefs, MONDAY, WEEK_END, now=MONDAY,
                     locked=locked,
                     extra_windows=[(utc(2026, 8, 10, 18),
                                     utc(2026, 8, 10, 21))])

    assert before.unmet
    assert after.unmet == ()
    assert len(after.new_periods) == 2
