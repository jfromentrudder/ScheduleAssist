"""Unit tests for the period-allocation engine.

The engine is pure, so these need no database, no app, and no network — just
datetimes in and periods out.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from app.scheduler import (
    BusyBlock,
    Prefs,
    Task,
    available_slots,
    generate,
)

# Mon 2026-08-10 through Fri 2026-08-14, a plain non-DST week.
MONDAY = datetime(2026, 8, 10, tzinfo=timezone.utc)
WEEK_END = MONDAY + timedelta(days=7)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def prefs() -> Prefs:
    """9-5 UTC, Mon-Fri, 60-minute periods: eight slots a day, no arithmetic."""
    return Prefs(
        workdays=(0, 1, 2, 3, 4),
        day_start=time(9, 0),
        day_end=time(17, 0),
        period_minutes=60,
        timezone="UTC",
    )


def test_empty_schedule_produces_no_periods(prefs):
    plan = generate([], [], prefs, MONDAY, WEEK_END, now=MONDAY)
    assert plan.periods == ()
    assert plan.unmet == ()


def test_slots_respect_workdays_and_working_hours(prefs):
    slots = available_slots(prefs, [], MONDAY, WEEK_END, now=MONDAY)

    # Five workdays x eight hours, with the weekend excluded entirely.
    assert len(slots) == 40
    assert {start.weekday() for start, _ in slots} == {0, 1, 2, 3, 4}
    assert all(9 <= start.hour < 17 for start, _ in slots)
    assert slots[0] == (utc(2026, 8, 10, 9), utc(2026, 8, 10, 10))


def test_periods_never_overlap_a_busy_block(prefs):
    meeting = BusyBlock(utc(2026, 8, 10, 10), utc(2026, 8, 10, 12))
    task = Task(event_id=1, due_at=utc(2026, 8, 10, 17), prep_minutes=180)

    plan = generate([task], [meeting], prefs, MONDAY, WEEK_END, now=MONDAY)

    assert len(plan.periods) == 3
    for period in plan.periods:
        assert not (period.starts_at < meeting.ends_at
                    and period.ends_at > meeting.starts_at)
    # The 9am slot still fits before the meeting; the rest shift past it.
    assert plan.periods[0].starts_at == utc(2026, 8, 10, 9)
    assert plan.periods[1].starts_at == utc(2026, 8, 10, 12)


def test_partial_periods_are_discarded(prefs):
    # Leaves a 30-minute gap before the meeting — half a period, so unusable.
    meeting = BusyBlock(utc(2026, 8, 10, 9, 30), utc(2026, 8, 10, 17))
    slots = available_slots(prefs, [meeting], MONDAY,
                            MONDAY + timedelta(days=1), now=MONDAY)
    assert slots == []


def test_overlapping_busy_blocks_are_merged(prefs):
    overlapping = [
        BusyBlock(utc(2026, 8, 10, 9), utc(2026, 8, 10, 13)),
        BusyBlock(utc(2026, 8, 10, 11), utc(2026, 8, 10, 15)),
    ]
    slots = available_slots(prefs, overlapping, MONDAY,
                            MONDAY + timedelta(days=1), now=MONDAY)
    assert slots == [
        (utc(2026, 8, 10, 15), utc(2026, 8, 10, 16)),
        (utc(2026, 8, 10, 16), utc(2026, 8, 10, 17)),
    ]


def test_prep_is_rounded_up_to_whole_periods(prefs):
    # 90 minutes of prep does not fit in one 60-minute period.
    task = Task(event_id=1, due_at=utc(2026, 8, 12, 9), prep_minutes=90)
    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY)
    assert len(plan.periods) == 2


def test_task_without_a_prep_estimate_still_gets_a_period(prefs):
    """NULL prep means unknown, not zero — inferred deadlines rely on this."""
    task = Task(event_id=1, due_at=utc(2026, 8, 12, 9), prep_minutes=None)
    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY)
    assert len(plan.periods) == 1
    assert plan.unmet == ()


def test_periods_land_before_the_deadline(prefs):
    task = Task(event_id=1, due_at=utc(2026, 8, 11, 12), prep_minutes=600)
    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY)

    assert plan.periods
    assert all(p.ends_at <= task.due_at for p in plan.periods)


def test_earlier_deadline_wins_contested_slots(prefs):
    # Both want Monday; only the urgent one can have it.
    urgent = Task(event_id=2, due_at=utc(2026, 8, 10, 17), prep_minutes=480)
    relaxed = Task(event_id=1, due_at=utc(2026, 8, 14, 17), prep_minutes=60)

    plan = generate([relaxed, urgent], [], prefs, MONDAY, WEEK_END, now=MONDAY)

    monday = [p for p in plan.periods if p.starts_at.day == 10]
    assert len(monday) == 8
    assert all(p.event_ids == (2,) for p in monday)
    # The relaxed task is not starved, just pushed to Tuesday.
    assert [p for p in plan.periods if p.event_ids ==
            (1,)][0].starts_at.day == 11


def test_overloaded_day_reports_what_did_not_fit(prefs):
    # 16 hours of prep due at the end of an 8-hour day.
    task = Task(event_id=1, due_at=utc(2026, 8, 10, 17), prep_minutes=960)
    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY)

    assert len(plan.periods) == 8
    assert len(plan.unmet) == 1
    assert plan.unmet[0].periods_needed == 16
    assert plan.unmet[0].periods_allocated == 8
    assert plan.unmet[0].reason == "no free time before deadline"


def test_overdue_task_is_reported_not_scheduled(prefs):
    task = Task(event_id=1, due_at=utc(2026, 8, 9, 12), prep_minutes=60)
    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=MONDAY)

    assert plan.periods == ()
    assert plan.unmet[0].reason == "overdue"


def test_nothing_is_scheduled_in_the_past(prefs):
    """Regenerating mid-week must not fill in slots that have already gone."""
    task = Task(event_id=1, due_at=utc(2026, 8, 14, 17), prep_minutes=60)
    midday = utc(2026, 8, 12, 13, 30)

    plan = generate([task], [], prefs, MONDAY, WEEK_END, now=midday)

    assert plan.periods[0].starts_at >= midday


def test_output_is_deterministic(prefs):
    tasks = [
        Task(event_id=3, due_at=utc(2026, 8, 13, 9), prep_minutes=120),
        Task(event_id=1, due_at=utc(2026, 8, 11, 9), prep_minutes=60),
        Task(event_id=2, due_at=utc(2026, 8, 11, 9), prep_minutes=60),
    ]
    busy = [BusyBlock(utc(2026, 8, 10, 10), utc(2026, 8, 10, 12))]

    first = generate(tasks, busy, prefs, MONDAY, WEEK_END, now=MONDAY)
    # Same inputs in a different order must still give the same schedule.
    second = generate(list(reversed(tasks)), busy,
                      prefs, MONDAY, WEEK_END, now=MONDAY)

    assert first == second


def test_naive_datetimes_are_treated_as_utc(prefs):
    """SQLite and hand-built fixtures hand back naive values; comparing a
    naive and an aware datetime raises, so the engine normalizes on entry."""
    task = Task(event_id=1, due_at=datetime(2026, 8, 12, 9), prep_minutes=60)
    busy = [BusyBlock(datetime(2026, 8, 10, 9), datetime(2026, 8, 10, 17))]

    plan = generate([task], busy, prefs, MONDAY, WEEK_END, now=MONDAY)

    assert len(plan.periods) == 1
    assert plan.periods[0].starts_at == utc(2026, 8, 11, 9)


def test_working_hours_follow_the_users_timezone(prefs):
    """9am Los Angeles is 16:00 or 17:00 UTC depending on the season."""
    la = Prefs(
        workdays=(0, 1, 2, 3, 4),
        day_start=time(9, 0),
        day_end=time(17, 0),
        period_minutes=60,
        timezone="America/Los_Angeles",
    )
    slots = available_slots(la, [], MONDAY, MONDAY + timedelta(days=1),
                            now=MONDAY)

    # PDT is UTC-7 in August.
    assert slots[0] == (utc(2026, 8, 10, 16), utc(2026, 8, 10, 17))


def test_workday_tracks_dst_rather_than_drifting():
    """Across a DST boundary the workday moves in UTC but stays 9am local."""
    la = Prefs(
        workdays=(0, 1, 2, 3, 4),
        day_start=time(9, 0),
        day_end=time(10, 0),
        period_minutes=60,
        timezone="America/Los_Angeles",
    )
    # US DST ends Sunday 2026-11-01, between these two Mondays.
    before = utc(2026, 10, 26)
    after = utc(2026, 11, 2)

    first = available_slots(la, [], before, before + timedelta(days=1),
                            now=before)
    second = available_slots(la, [], after, after + timedelta(days=1),
                             now=after)

    assert first[0][0].hour == 16  # PDT, UTC-7
    assert second[0][0].hour == 17  # PST, UTC-8
