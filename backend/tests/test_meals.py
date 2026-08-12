"""Tests for the meal break.

A schedule that books someone solidly through lunch is not one they will
follow, so the engine claims that time before it allocates any work. The claim
is greedy — the preferred length first, then shorter ones — because a rushed
meal beats no meal.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from app.scheduler import (
    MIN_MEAL_MINUTES,
    BusyBlock,
    Prefs,
    Task,
    generate,
    reserve_meals,
)

MONDAY = datetime(2026, 8, 10, tzinfo=timezone.utc)
WEEK_END = MONDAY + timedelta(days=7)
ONE_DAY = MONDAY + timedelta(days=1)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def prefs() -> Prefs:
    """9-5 UTC, Mon-Fri, 60-minute periods."""
    return Prefs(
        workdays=(0, 1, 2, 3, 4),
        day_start=time(9, 0),
        day_end=time(17, 0),
        period_minutes=60,
        timezone="UTC",
    )


def meals(prefs, busy=(), minutes=60, existing=(), end=ONE_DAY):
    return reserve_meals(prefs, list(busy), MONDAY, end, MONDAY, minutes,
                         existing)


# --- Claiming the time --------------------------------------------------

def test_a_meal_is_reserved_on_a_workday(prefs):
    reserved = meals(prefs)

    assert len(reserved) == 1
    start, end = reserved[0]
    assert end - start == timedelta(minutes=60)


def test_the_meal_lands_in_the_middle_of_the_day(prefs):
    """Nobody calls 09:00 lunch."""
    start, end = meals(prefs)[0]
    # Midpoint of a 9-17 day is 13:00, so an hour centred on it is 12:30-13:30.
    assert start == utc(2026, 8, 10, 12, 30)
    assert end == utc(2026, 8, 10, 13, 30)


def test_one_meal_per_workday(prefs):
    reserved = meals(prefs, end=WEEK_END)
    assert len(reserved) == 5
    assert {start.weekday() for start, _ in reserved} == {0, 1, 2, 3, 4}


def test_no_meal_on_a_day_that_is_not_worked(prefs):
    saturday = Prefs(workdays=(5,), day_start=prefs.day_start,
                     day_end=prefs.day_end, period_minutes=60, timezone="UTC")
    assert meals(saturday) == []


def test_the_meal_follows_the_working_day(prefs):
    """An early shift eats early."""
    early = Prefs(workdays=(0,), day_start=time(6, 0), day_end=time(14, 0),
                  period_minutes=60, timezone="UTC")
    start, _ = meals(early)[0]
    assert start == utc(2026, 8, 10, 9, 30)  # centred on the 10:00 midpoint


# --- Greedy fallback ----------------------------------------------------

def test_the_preferred_length_is_taken_when_there_is_room(prefs):
    start, end = meals(prefs, minutes=90)[0]
    assert end - start == timedelta(minutes=90)


def test_a_shorter_meal_is_taken_when_the_middle_is_busy(prefs):
    """Greedy: 60 will not fit, so try 45, then 30."""
    # Leaves exactly 45 minutes free around the middle of the day.
    busy = [
        BusyBlock(utc(2026, 8, 10, 9), utc(2026, 8, 10, 12, 45)),
        BusyBlock(utc(2026, 8, 10, 13, 30), utc(2026, 8, 10, 17)),
    ]
    start, end = meals(prefs, busy)[0]
    assert end - start == timedelta(minutes=45)


def test_the_shortest_meal_is_still_taken(prefs):
    busy = [
        BusyBlock(utc(2026, 8, 10, 9), utc(2026, 8, 10, 12, 45)),
        BusyBlock(utc(2026, 8, 10, 13, 15), utc(2026, 8, 10, 17)),
    ]
    start, end = meals(prefs, busy)[0]
    assert end - start == timedelta(minutes=MIN_MEAL_MINUTES)


def test_a_fully_booked_day_gets_no_meal(prefs):
    """Better none than a fifteen-minute one that pretends to be a break."""
    busy = [BusyBlock(utc(2026, 8, 10, 9), utc(2026, 8, 10, 17))]
    assert meals(prefs, busy) == []


def test_a_preference_below_the_fallbacks_is_not_exceeded(prefs):
    """Asking for 30 must never yield 45 just because there was room."""
    start, end = meals(prefs, minutes=30)[0]
    assert end - start == timedelta(minutes=30)


def test_the_meal_never_drifts_to_the_edges_of_the_day(prefs):
    """Only the morning is free, and 09:00 is not lunch."""
    busy = [BusyBlock(utc(2026, 8, 10, 9, 45), utc(2026, 8, 10, 17))]
    assert meals(prefs, busy) == []


# --- The user's own meal wins -------------------------------------------

def test_a_users_own_meal_replaces_the_generated_one(prefs):
    own = [(utc(2026, 8, 10, 11), utc(2026, 8, 10, 11, 30))]
    assert meals(prefs, existing=own) == []


def test_only_the_overridden_day_is_skipped(prefs):
    own = [(utc(2026, 8, 10, 11), utc(2026, 8, 10, 11, 30))]
    reserved = meals(prefs, existing=own, end=WEEK_END)

    assert len(reserved) == 4
    assert all(start.weekday() != 0 for start, _ in reserved)


def test_a_short_custom_meal_is_respected_as_chosen(prefs):
    """The user asked for twenty minutes; the app does not argue."""
    own = [(utc(2026, 8, 10, 12), utc(2026, 8, 10, 12, 20))]
    assert meals(prefs, existing=own) == []


# --- Meals and work together --------------------------------------------

def test_work_is_never_scheduled_over_the_meal(prefs):
    task = Task(event_id=1, due_at=utc(2026, 8, 14, 17), prep_minutes=600)
    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY,
                    meal_minutes=60)

    assert plan.meals
    for meal_start, meal_end in plan.meals:
        for period in plan.periods:
            assert not (period.starts_at < meal_end
                        and period.ends_at > meal_start)


def test_the_meal_is_claimed_before_work_is_allocated(prefs):
    """A packed day must not squeeze the meal out; work loses instead."""
    task = Task(event_id=1, due_at=utc(2026, 8, 10, 17), prep_minutes=600)

    without = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY)
    with_meal = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY,
                         meal_minutes=60)

    assert len(with_meal.periods) < len(without.periods)
    # Monday is the contested day, and it still gets its meal.
    assert any(start.day == 10 for start, _ in with_meal.meals)


def test_no_meal_policy_means_no_meal(prefs):
    """The engine invents nothing; the caller passes the preference."""
    plan = generate([], [], prefs, MONDAY, WEEK_END, now=MONDAY)
    assert plan.meals == ()


def test_meals_are_deterministic(prefs):
    busy = [BusyBlock(utc(2026, 8, 10, 11), utc(2026, 8, 10, 12))]
    first = generate([], busy, prefs, MONDAY, WEEK_END, now=MONDAY,
                     meal_minutes=60)
    second = generate([], busy, prefs, MONDAY, WEEK_END, now=MONDAY,
                      meal_minutes=60)
    assert first.meals == second.meals
