"""Tests for removing periods, by hand and as a consequence of losing an event.

Two rules are load-bearing here. A settled period cannot be deleted without the
user confirming, because the horizon promised them it would stay put. And a
period that no longer serves any event has to go, because it is holding time
for work that does not exist — the failure mode is silent, since an empty
`period_events` link looks exactly like a meal break to any query that does not
check `kind`.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import (
    Calendar, CalendarConnection, CalendarKind, Event, EventSource, EventType,
    Period, PeriodKind,
)
from app.planning import clear_orphaned_periods
from app.integrations.sync import clear_calendar


def now() -> datetime:
    return datetime.now(timezone.utc)


def _period(user, *, days_ahead: int, events=(), kind=PeriodKind.WORK) -> Period:
    """A period `days_ahead` days from now, at an hour that avoids midnight.

    Built relative to the clock rather than a fixed date because whether it is
    settled depends on the horizon, which moves with today.
    """
    start = now() + timedelta(days=days_ahead, hours=2)
    period = Period(user_id=user.id, starts_at=start,
                    ends_at=start + timedelta(minutes=50), kind=kind)
    period.events = list(events)
    return period


def _deadline(user, title="Essay", *, days_ahead=10) -> Event:
    return Event(
        user_id=user.id, title=title, event_type=EventType.DEADLINE,
        source=EventSource.MANUAL, due_at=now() + timedelta(days=days_ahead),
        expected_prep_minutes=100,
    )


# --- Deleting a period by hand ------------------------------------------

def test_an_open_period_is_deleted_without_ceremony(client, db_session, user):
    """Beyond the horizon the next generation would move it anyway."""
    period = _period(user, days_ahead=20)
    db_session.add(period)
    db_session.commit()

    assert client.delete(f"/api/periods/{period.id}").status_code == 204
    assert db_session.get(Period, period.id) is None


def test_a_settled_period_warns_before_it_is_deleted(client, db_session, user):
    """Inside the horizon the user was promised this would stay put."""
    period = _period(user, days_ahead=1)
    db_session.add(period)
    db_session.commit()

    response = client.delete(f"/api/periods/{period.id}")

    assert response.status_code == 409
    assert "settled" in response.json()["detail"]
    # Nothing removed: the warning is a question, not a result.
    assert db_session.get(Period, period.id) is not None


def test_a_settled_period_is_deleted_once_confirmed(client, db_session, user):
    period = _period(user, days_ahead=1)
    db_session.add(period)
    db_session.commit()

    response = client.delete(
        f"/api/periods/{period.id}", params={"confirm": "true"})

    assert response.status_code == 204
    assert db_session.get(Period, period.id) is None


def test_a_meal_break_can_be_deleted_too(client, db_session, user):
    """A held meal is still a generated block the user may not want."""
    meal = _period(user, days_ahead=20, kind=PeriodKind.MEAL)
    db_session.add(meal)
    db_session.commit()

    assert client.delete(f"/api/periods/{meal.id}").status_code == 204
    assert db_session.get(Period, meal.id) is None


def test_deleting_a_period_leaves_the_deadline_alone(client, db_session, user):
    """The work still exists; only the block held for it is gone."""
    deadline = _deadline(user)
    db_session.add(deadline)
    db_session.commit()
    period = _period(user, days_ahead=20, events=[deadline])
    db_session.add(period)
    db_session.commit()

    assert client.delete(f"/api/periods/{period.id}").status_code == 204
    assert db_session.get(Event, deadline.id) is not None


def test_another_users_period_is_not_found(client, db_session, user):
    """Ownership is checked, so ids are not a way to reach someone else's data."""
    from app.models import User

    stranger = User(email="someone@else.example", display_name="Else")
    db_session.add(stranger)
    db_session.commit()
    theirs = _period(stranger, days_ahead=20)
    db_session.add(theirs)
    db_session.commit()

    assert client.delete(f"/api/periods/{theirs.id}").status_code == 404
    assert db_session.get(Period, theirs.id) is not None


def test_an_unknown_period_is_not_found(client):
    assert client.delete("/api/periods/9999").status_code == 404


# --- Losing the event a period served -----------------------------------

def test_deleting_a_deadline_clears_the_periods_it_caused(
        client, db_session, user):
    deadline = _deadline(user)
    db_session.add(deadline)
    db_session.commit()
    db_session.add_all([
        _period(user, days_ahead=2, events=[deadline]),
        _period(user, days_ahead=3, events=[deadline]),
    ])
    db_session.commit()
    assert db_session.query(Period).count() == 2

    assert client.delete(f"/api/events/{deadline.id}").status_code == 204

    # Cleared even though one of them was settled: the freeze protects a plan
    # the user can still act on, and there is nothing left to act on.
    assert db_session.query(Period).count() == 0


def test_a_period_shared_with_another_deadline_survives(
        client, db_session, user):
    """One study block can serve two deadlines; the other still needs it."""
    going = _deadline(user, "Essay")
    staying = _deadline(user, "Lab report")
    db_session.add_all([going, staying])
    db_session.commit()
    shared = _period(user, days_ahead=20, events=[going, staying])
    db_session.add(shared)
    db_session.commit()

    assert client.delete(f"/api/events/{going.id}").status_code == 204

    # The link row is removed by the database cascade, which the session's
    # already-loaded collection knows nothing about until it is expired.
    db_session.expire_all()
    kept = db_session.get(Period, shared.id)
    assert kept is not None
    assert [e.id for e in kept.events] == [staying.id]


def test_a_meal_period_is_never_treated_as_an_orphan(db_session, user):
    """Meals serve no event by design, which is the trap this rule sidesteps."""
    meal = _period(user, days_ahead=2, kind=PeriodKind.MEAL)
    db_session.add(meal)
    db_session.commit()

    assert clear_orphaned_periods(db_session, user.id) == 0
    assert db_session.get(Period, meal.id) is not None


def test_the_cleanup_leaves_other_users_periods_alone(db_session, user):
    from app.models import User

    stranger = User(email="other@example.com")
    db_session.add(stranger)
    db_session.commit()
    theirs = _period(stranger, days_ahead=2)
    db_session.add(theirs)
    db_session.commit()

    assert clear_orphaned_periods(db_session, user.id) == 0
    assert db_session.get(Period, theirs.id) is not None


# --- Losing the calendar an event came from -----------------------------

@pytest.fixture
def calendar(db_session, user):
    connection = CalendarConnection(
        user_id=user.id, provider="google", provider_account_id="sub-1",
        account_email="owner@example.com", default_kind=CalendarKind.SCHOOL,
        access_token="access", refresh_token="refresh", scopes="",
    )
    db_session.add(connection)
    db_session.commit()
    record = Calendar(
        calendar_connection_id=connection.id,
        provider_calendar_id="owner@example.com",
        name="Primary", is_primary=True, selected=True,
        kind=CalendarKind.SCHOOL,
    )
    db_session.add(record)
    db_session.commit()
    return record


def _imported_deadline(user, calendar) -> Event:
    return Event(
        user_id=user.id, title="Essay 2 due", event_type=EventType.DEADLINE,
        source=EventSource.IMPORTED, calendar_id=calendar.id,
        provider_event_id="g-1", due_at=now() + timedelta(days=10),
        expected_prep_minutes=180,
    )


def test_unticking_a_calendar_clears_the_periods_it_caused(
        db_session, user, calendar):
    """`clear_calendar` bulk-deletes, so only the database cascade fires and
    the periods are unlinked rather than removed."""
    deadline = _imported_deadline(user, calendar)
    db_session.add(deadline)
    db_session.commit()
    db_session.add(_period(user, days_ahead=20, events=[deadline]))
    db_session.commit()

    assert clear_calendar(db_session, calendar) == 1

    assert db_session.query(Event).count() == 0
    assert db_session.query(Period).count() == 0


def test_disconnecting_a_calendar_clears_its_periods(
        client, db_session, user, calendar):
    deadline = _imported_deadline(user, calendar)
    db_session.add(deadline)
    db_session.commit()
    db_session.add(_period(user, days_ahead=20, events=[deadline]))
    db_session.commit()

    connection_id = calendar.calendar_connection_id
    # Revocation is a network call; the local removal is what is under test.
    with patch("app.integrations.tokens.httpx.post"):
        response = client.delete(f"/api/calendars/{connection_id}")

    assert response.status_code == 204
    assert db_session.query(Event).count() == 0
    assert db_session.query(Period).count() == 0


def test_a_manual_period_survives_a_disconnect(
        client, db_session, user, calendar):
    """Work for a deadline the user typed in themselves is not the calendar's
    to take away."""
    mine = _deadline(user, "My own deadline")
    db_session.add(mine)
    db_session.commit()
    db_session.add(_period(user, days_ahead=20, events=[mine]))
    db_session.commit()

    with patch("app.integrations.tokens.httpx.post"):
        client.delete(f"/api/calendars/{calendar.calendar_connection_id}")

    assert db_session.query(Period).count() == 1
