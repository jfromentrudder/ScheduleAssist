"""Tests for the schedule API: the adapter between the ORM and the engine.

The allocation rules themselves are covered in test_scheduler.py and
test_horizon.py; what matters here is that rows map correctly in both
directions and that a shortfall stops the write.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Availability, Event, EventSource, EventType, Period, PeriodKind,
)
from app.api.schedule import apply_plan, build_plan, split_events


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def work_periods(db):
    """Meal breaks are periods too; these tests are about allocated work."""
    return db.query(Period).filter(Period.kind == PeriodKind.WORK).all()


def aware(value: datetime) -> datetime:
    """SQLite hands stored datetimes back without a timezone; Postgres does
    not. Normalize before comparing, exactly as the engine does."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def make_deadline(user, *, due_at, prep=None, title="Essay"):
    return Event(
        user_id=user.id, title=title, event_type=EventType.DEADLINE,
        source=EventSource.MANUAL, due_at=due_at, expected_prep_minutes=prep,
    )


def make_meeting(user, *, starts_at, ends_at, all_day=False, title="Standup"):
    return Event(
        user_id=user.id, title=title, event_type=EventType.ONE_TIME,
        source=EventSource.IMPORTED, starts_at=starts_at, ends_at=ends_at,
        is_all_day=all_day,
    )


# --- Mapping ------------------------------------------------------------

def test_deadlines_become_tasks_and_meetings_become_busy(db_session, user):
    db_session.add_all([
        make_deadline(user, due_at=utc(2026, 8, 14, 17), prep=120),
        make_meeting(user, starts_at=utc(2026, 8, 10, 10),
                     ends_at=utc(2026, 8, 10, 11)),
    ])
    db_session.commit()

    inputs = split_events(db_session.query(Event).all())

    assert len(inputs.tasks) == 1 and inputs.tasks[0].prep_minutes == 120
    assert len(inputs.busy) == 1
    assert inputs.windows == []


def test_all_day_events_are_not_treated_as_busy(db_session, user):
    """One 'Conference' entry must not blank out a whole workable day."""
    event = make_meeting(
        user, starts_at=utc(2026, 8, 10), ends_at=utc(2026, 8, 11),
        all_day=True, title="Conference")
    event.availability = Availability.FREE
    db_session.add(event)
    db_session.commit()

    inputs = split_events(db_session.query(Event).all())

    assert inputs.busy == []
    assert inputs.windows == []


def test_a_work_window_offers_time_rather_than_blocking_it(db_session, user):
    """A shift at work is when the work happens, not a wall around it."""
    shift = make_meeting(user, starts_at=utc(2026, 8, 10, 9),
                         ends_at=utc(2026, 8, 10, 17), title="At work")
    shift.availability = Availability.WORK_WINDOW
    db_session.add(shift)
    db_session.commit()

    inputs = split_events(db_session.query(Event).all())

    assert inputs.busy == []
    assert inputs.windows == [(shift.starts_at, shift.ends_at)]


def test_a_meal_both_blocks_time_and_settles_the_day(db_session, user):
    """It occupies its hour, and stops another break being reserved."""
    lunch = make_meeting(user, starts_at=utc(2026, 8, 10, 12),
                         ends_at=utc(2026, 8, 10, 13), title="Lunch")
    lunch.availability = Availability.MEAL
    db_session.add(lunch)
    db_session.commit()

    inputs = split_events(db_session.query(Event).all())

    assert len(inputs.busy) == 1
    assert inputs.meals == [(lunch.starts_at, lunch.ends_at)]


# --- Reading the feed ---------------------------------------------------

def test_get_schedule_reports_the_horizon(client):
    response = client.get("/api/schedule", params={
        "start": "2026-08-10T00:00:00Z", "end": "2026-08-17T00:00:00Z"})

    assert response.status_code == 200
    body = response.json()
    assert body["preferences"]["schedule_horizon_days"] == 5
    assert body["horizon_ends_at"] is not None


def test_get_schedule_rejects_a_backwards_range(client):
    response = client.get("/api/schedule", params={
        "start": "2026-08-17T00:00:00Z", "end": "2026-08-10T00:00:00Z"})
    assert response.status_code == 422


def test_get_schedule_rejects_an_oversized_range(client):
    response = client.get("/api/schedule", params={
        "start": "2026-01-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"})
    assert response.status_code == 422


# --- Generating ---------------------------------------------------------

def test_generate_writes_periods_for_a_deadline(client, db_session, user):
    due = datetime.now(timezone.utc) + timedelta(days=10)
    db_session.add(make_deadline(user, due_at=due, prep=120))
    db_session.commit()

    response = client.post("/api/schedule/generate", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["committed"] is True
    assert body["periods_created"] == 3  # 120 minutes in 50-minute periods
    assert len(work_periods(db_session)) == 3


def test_generated_periods_link_back_to_their_event(client, db_session, user):
    due = datetime.now(timezone.utc) + timedelta(days=10)
    event = make_deadline(user, due_at=due, prep=50)
    db_session.add(event)
    db_session.commit()

    client.post("/api/schedule/generate", json={})

    periods = work_periods(db_session)
    assert len(periods) == 1
    assert [e.id for e in periods[0].events] == [event.id]


def test_generate_is_idempotent(client, db_session, user):
    """Running twice with unchanged inputs leaves the same schedule."""
    due = datetime.now(timezone.utc) + timedelta(days=10)
    db_session.add(make_deadline(user, due_at=due, prep=100))
    db_session.commit()

    client.post("/api/schedule/generate", json={})
    first = {(p.starts_at, p.ends_at) for p in work_periods(db_session)}
    db_session.expire_all()
    client.post("/api/schedule/generate", json={})
    second = {(p.starts_at, p.ends_at) for p in work_periods(db_session)}

    assert first == second


def test_generate_schedules_around_a_meeting(client, db_session, user):
    """Periods must not overlap committed time that came from a calendar."""
    now = datetime.now(timezone.utc)
    start = (now + timedelta(days=8)).replace(
        hour=9, minute=0, second=0, microsecond=0)
    db_session.add_all([
        make_deadline(user, due_at=now + timedelta(days=12), prep=50),
        make_meeting(user, starts_at=start, ends_at=start + timedelta(hours=8)),
    ])
    db_session.commit()

    client.post("/api/schedule/generate", json={})

    assert len(work_periods(db_session)) > 0
    for period in work_periods(db_session):
        assert not (aware(period.starts_at) < start + timedelta(hours=8)
                    and aware(period.ends_at) > start)


def test_shortfall_is_reported_without_writing(client, db_session, user):
    """The user has to be asked before their committed week is disturbed."""
    now = datetime.now(timezone.utc)
    # Far more prep than the next two days can hold.
    db_session.add(make_deadline(
        user, due_at=now + timedelta(days=2), prep=10_000))
    db_session.commit()

    response = client.post("/api/schedule/generate", json={})
    body = response.json()

    assert body["committed"] is False
    assert body["unmet"]
    assert set(body["options"]) == {"rebuild", "extend_hours", "accept_unmet"}
    assert len(work_periods(db_session)) == 0


def test_accepting_the_shortfall_commits_what_fits(client, db_session, user):
    now = datetime.now(timezone.utc)
    db_session.add(make_deadline(
        user, due_at=now + timedelta(days=2), prep=10_000))
    db_session.commit()

    response = client.post("/api/schedule/generate",
                           json={"accept_unmet": True})
    body = response.json()

    assert body["committed"] is True
    assert body["unmet"]
    assert len(work_periods(db_session)) > 0


def test_extending_hours_commits_directly(client, db_session, user):
    """Supplying extra availability *is* the user's answer, so it is applied."""
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=2)
    db_session.add(make_deadline(user, due_at=due, prep=50))
    db_session.commit()

    evening = (now + timedelta(days=1)).replace(hour=19, minute=0,
                                                second=0, microsecond=0)
    response = client.post("/api/schedule/generate", json={
        "extra_windows": [{
            "starts_at": evening.isoformat(),
            "ends_at": (evening + timedelta(hours=2)).isoformat(),
        }],
    })

    assert response.json()["committed"] is True


def test_rebuild_strategy_commits_without_asking(client, db_session, user):
    now = datetime.now(timezone.utc)
    db_session.add(make_deadline(
        user, due_at=now + timedelta(days=2), prep=10_000))
    db_session.commit()

    response = client.post("/api/schedule/generate",
                           json={"strategy": "rebuild"})

    assert response.json()["committed"] is True


def test_generate_rejects_a_backwards_extra_window(client):
    now = datetime.now(timezone.utc)
    response = client.post("/api/schedule/generate", json={
        "extra_windows": [{
            "starts_at": (now + timedelta(hours=2)).isoformat(),
            "ends_at": now.isoformat(),
        }],
    })
    assert response.status_code == 422


# --- The horizon, end to end through the database -----------------------
# These drive build_plan/apply_plan directly rather than the endpoint, because
# only they let `now` be pinned to a known Monday. The endpoint reads the real
# clock, so a suite run on a weekend would otherwise be testing nothing.

MONDAY = utc(2026, 8, 10, 8)  # An hour before the 9am workday opens.
FORTNIGHT = MONDAY + timedelta(days=14)


def regenerate(db_session, user, now=MONDAY, respect_horizon=True, extra=()):
    plan = build_plan(db_session, user, MONDAY, FORTNIGHT, now,
                      respect_horizon, list(extra))
    apply_plan(db_session, user, plan, MONDAY, FORTNIGHT, now)
    return plan


def test_committed_periods_survive_a_new_deadline(db_session, user):
    """The whole point of the horizon: today's plan does not move."""
    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 21, 17), prep=200, title="Essay"))
    db_session.commit()
    regenerate(db_session, user)

    boundary = utc(2026, 8, 15)  # 5-day horizon from Monday.
    before = {p.id: (p.starts_at, p.ends_at)
              for p in work_periods(db_session)
              if aware(p.starts_at) < boundary}
    assert before, "expected the first pass to commit work inside the horizon"

    # A second deadline arrives that would otherwise be front-loaded on top.
    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 20, 17), prep=100, title="Lab"))
    db_session.commit()
    regenerate(db_session, user)

    after = {p.id: (p.starts_at, p.ends_at)
             for p in work_periods(db_session)}
    for period_id, times in before.items():
        assert period_id in after, "a locked period was deleted"
        assert after[period_id] == times, "a locked period moved"


def test_new_work_fills_gaps_inside_the_horizon(db_session, user):
    """Additive: untouched free time inside the horizon is still usable."""
    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 21, 17), prep=100, title="Essay"))
    db_session.commit()
    regenerate(db_session, user)
    first_pass = len(work_periods(db_session))

    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 12, 17), prep=100, title="Quiz"))
    db_session.commit()
    plan = regenerate(db_session, user)

    assert len(work_periods(db_session)) > first_pass
    assert plan.unmet == ()


def test_rebuild_may_move_periods_the_horizon_had_frozen(db_session, user):
    """The escape hatch does what it says: locked periods are fair game."""
    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 21, 17), prep=2000, title="Essay"))
    db_session.commit()
    regenerate(db_session, user)
    before = {p.id for p in work_periods(db_session)}

    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 11, 17), prep=400, title="Exam"))
    db_session.commit()
    regenerate(db_session, user, respect_horizon=False)

    after = {p.id for p in work_periods(db_session)}
    assert before != after


def test_periods_already_under_way_are_never_rewritten(db_session, user):
    """Regenerating at midday must not delete this morning's schedule."""
    db_session.add(make_deadline(
        user, due_at=utc(2026, 8, 21, 17), prep=200, title="Essay"))
    db_session.commit()
    regenerate(db_session, user)

    morning = {p.id for p in work_periods(db_session)
               if aware(p.starts_at) < utc(2026, 8, 10, 12)}
    assert morning, "expected work scheduled before midday"

    # A full rebuild, from midday, with the horizon ignored entirely.
    regenerate(db_session, user, now=utc(2026, 8, 10, 12),
               respect_horizon=False)

    surviving = {p.id for p in work_periods(db_session)}
    assert morning <= surviving


# --- The horizon setting ------------------------------------------------

def test_horizon_defaults_to_a_work_week(client):
    body = client.get("/api/account").json()
    assert body["schedule_horizon_days"] == 5
    assert body["schedule_horizon_warning"] is None


@pytest.mark.parametrize("days", [1, 21])
def test_extreme_horizons_come_back_with_a_warning(client, days):
    body = client.patch(
        "/api/account", json={"schedule_horizon_days": days}).json()
    assert body["schedule_horizon_days"] == days
    assert body["schedule_horizon_warning"]


@pytest.mark.parametrize("days", [0, 22, -1])
def test_horizon_outside_the_allowed_range_is_rejected(client, days):
    response = client.patch(
        "/api/account", json={"schedule_horizon_days": days})
    assert response.status_code == 422


def test_updating_the_horizon_leaves_appearance_alone(client):
    client.patch("/api/account", json={"theme": "tide"})
    body = client.patch(
        "/api/account", json={"schedule_horizon_days": 10}).json()
    assert body["theme"] == "tide"
