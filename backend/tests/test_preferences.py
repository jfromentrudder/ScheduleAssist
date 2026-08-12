"""Tests for the scheduling preferences the settings screen exposes (#15).

These are the values the generator reads directly, so a bad one is not a
cosmetic problem — it either produces a nonsensical schedule or none at all.
Every bound here is enforced in three places: the engine's constants, this
API, and a CHECK constraint.
"""

import pytest

from app.models import User
from app.core.scheduler import (
    MAX_LUNCH_MINUTES, MAX_PERIOD_MINUTES, MIN_LUNCH_MINUTES,
    MIN_PERIOD_MINUTES,
)


def patch(client, **fields):
    return client.patch("/api/account", json=fields)


# --- Defaults -----------------------------------------------------------

def test_defaults_are_a_standard_working_week(client):
    body = client.get("/api/account").json()

    assert body["workdays"] == [0, 1, 2, 3, 4]
    assert body["day_start"] == "09:00:00"
    assert body["day_end"] == "17:00:00"
    assert body["period_minutes"] == 50
    assert body["lunch_minutes"] == 60
    assert body["timezone"] == "UTC"


# --- Workdays -----------------------------------------------------------

def test_workdays_can_be_changed(client, db_session):
    body = patch(client, workdays=[0, 2, 4]).json()
    assert body["workdays"] == [0, 2, 4]
    assert db_session.query(User).one().workdays == [0, 2, 4]


def test_workdays_are_stored_in_one_canonical_form(client):
    """Sorted and de-duplicated, so two equivalent payloads store identically."""
    assert patch(client, workdays=[4, 0, 2, 0]).json()["workdays"] == [0, 2, 4]


def test_working_seven_days_is_allowed(client):
    assert patch(client, workdays=[0, 1, 2, 3, 4, 5, 6]).status_code == 200


def test_working_no_days_is_allowed(client):
    """Odd, but it is the user's call — and it generates nothing, not an error."""
    assert patch(client, workdays=[]).status_code == 200


@pytest.mark.parametrize("days", [[7], [-1], [0, 9]])
def test_days_outside_the_week_are_rejected(client, days):
    assert patch(client, workdays=days).status_code == 422


# --- The working day ----------------------------------------------------

def test_day_bounds_can_be_changed(client):
    body = patch(client, day_start="07:30:00", day_end="19:00:00").json()
    assert body["day_start"] == "07:30:00"
    assert body["day_end"] == "19:00:00"


def test_a_day_ending_before_it_starts_is_rejected(client):
    response = patch(client, day_start="17:00:00", day_end="09:00:00")
    assert response.status_code == 422
    assert "end after it starts" in response.json()["detail"]


def test_a_zero_length_day_is_rejected(client):
    assert patch(client, day_start="09:00:00",
                 day_end="09:00:00").status_code == 422


def test_one_end_is_validated_against_the_stored_other(client):
    """Sending only day_start must still be checked against the saved day_end."""
    response = patch(client, day_start="18:00:00")  # stored day_end is 17:00
    assert response.status_code == 422


def test_a_valid_single_end_is_accepted(client):
    assert patch(client, day_start="08:00:00").status_code == 200


# --- Period length ------------------------------------------------------

def test_period_length_can_be_changed(client):
    assert patch(client, period_minutes=25).json()["period_minutes"] == 25


@pytest.mark.parametrize("minutes", [MIN_PERIOD_MINUTES, MAX_PERIOD_MINUTES])
def test_the_period_bounds_themselves_are_allowed(client, minutes):
    assert patch(client, period_minutes=minutes).status_code == 200


@pytest.mark.parametrize("minutes", [0, MIN_PERIOD_MINUTES - 1,
                                     MAX_PERIOD_MINUTES + 1, -30])
def test_impossible_period_lengths_are_rejected(client, minutes):
    assert patch(client, period_minutes=minutes).status_code == 422


# --- Lunch --------------------------------------------------------------

def test_lunch_length_can_be_changed(client):
    assert patch(client, lunch_minutes=45).json()["lunch_minutes"] == 45


@pytest.mark.parametrize("minutes", [MIN_LUNCH_MINUTES, MAX_LUNCH_MINUTES])
def test_the_lunch_bounds_themselves_are_allowed(client, minutes):
    assert patch(client, lunch_minutes=minutes).status_code == 200


@pytest.mark.parametrize("minutes", [0, 29, 121, 480])
def test_a_meal_shorter_than_half_an_hour_is_rejected(client, minutes):
    """A meal is not optional, so there is a floor as well as a ceiling."""
    assert patch(client, lunch_minutes=minutes).status_code == 422


# --- Timezone -----------------------------------------------------------

def test_timezone_can_be_changed(client):
    body = patch(client, timezone="America/Los_Angeles").json()
    assert body["timezone"] == "America/Los_Angeles"


@pytest.mark.parametrize("zone", ["Mars/Olympus", "PST", ""])
def test_an_unknown_timezone_is_rejected(client, zone):
    """The engine calls ZoneInfo on this; a bad value would break generation."""
    assert patch(client, timezone=zone).status_code == 422


# --- Telling the client the schedule is now stale -----------------------

def test_changing_a_scheduling_preference_marks_the_schedule_stale(client):
    assert patch(client, day_start="08:00:00").json()["schedule_stale"] is True


def test_changing_appearance_does_not(client):
    """Picking a theme has nothing to do with when work happens."""
    assert patch(client, theme="tide").json()["schedule_stale"] is False


def test_changing_the_horizon_alone_does_not(client):
    """It changes what is protected next time, not where anything sits now."""
    assert patch(client, schedule_horizon_days=10).json()[
        "schedule_stale"] is False


@pytest.mark.parametrize("change", [
    {"timezone": "America/New_York"},
    {"day_start": "10:00:00"},
    {"workdays": [0, 1]},
    {"period_minutes": 30},
    {"lunch_minutes": 45},
])
def test_every_placement_preference_marks_the_schedule_stale(client, change):
    assert patch(client, **change).json()["schedule_stale"] is True


def test_saving_several_preferences_at_once(client):
    body = patch(client, workdays=[0, 1, 2], day_start="10:00:00",
                 day_end="16:00:00", period_minutes=30,
                 lunch_minutes=45).json()

    assert body["workdays"] == [0, 1, 2]
    assert body["period_minutes"] == 30
    assert body["lunch_minutes"] == 45
    assert body["schedule_stale"] is True


def test_a_rejected_update_changes_nothing(client, db_session):
    """One bad field must not leave the others half-applied."""
    patch(client, period_minutes=45)
    assert patch(client, period_minutes=30, day_end="01:00:00").status_code == 422
    assert db_session.query(User).one().period_minutes == 45


# --- Stale periods are actually corrected -------------------------------

def test_changing_timezone_moves_settled_periods_on_a_rebuild(
    client, db_session
):
    """The bug this guards: periods generated under the old zone sit inside
    the horizon, so an additive pass protects the very blocks that are wrong."""
    from datetime import datetime, timedelta, timezone

    from app.models import Event, EventSource, EventType, Period, PeriodKind

    due = datetime.now(timezone.utc) + timedelta(days=3)
    db_session.add(Event(
        user_id=db_session.query(User).one().id, title="Essay",
        event_type=EventType.DEADLINE, source=EventSource.MANUAL,
        due_at=due, expected_prep_minutes=100,
    ))
    db_session.commit()

    # Built while the account is still on UTC.
    client.post("/api/schedule/generate", json={})
    before = {p.starts_at for p in db_session.query(Period)
              .filter(Period.kind == PeriodKind.WORK)}
    assert before

    patch(client, timezone="America/New_York")

    # The additive default leaves them exactly where they were...
    client.post("/api/schedule/generate", json={})
    db_session.expire_all()
    additive = {p.starts_at for p in db_session.query(Period)
                .filter(Period.kind == PeriodKind.WORK)}
    assert additive >= before, "settled periods should survive an additive pass"

    # ...and only a full rebuild brings them into the new working hours.
    client.post("/api/schedule/generate", json={"strategy": "rebuild"})
    db_session.expire_all()
    after = {p.starts_at for p in db_session.query(Period)
             .filter(Period.kind == PeriodKind.WORK)}

    assert after
    assert after != before


# --- Preferences reach the generator ------------------------------------

def test_the_generator_reads_the_saved_preferences(client, db_session):
    from app.api.schedule import user_prefs

    patch(client, workdays=[0, 2], day_start="08:00:00", day_end="12:00:00",
          period_minutes=30, timezone="America/Los_Angeles")

    prefs = user_prefs(db_session.query(User).one())

    assert prefs.workdays == (0, 2)
    assert prefs.period_minutes == 30
    assert prefs.timezone == "America/Los_Angeles"
    assert prefs.day_start.hour == 8 and prefs.day_end.hour == 12
