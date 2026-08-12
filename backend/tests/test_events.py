"""Tests for creating and editing events, and for what each view shows.

These cover the foundation the generated view rests on: an event's
availability decides whether it blocks the day, offers time to work in, or is
just a label — and a user's correction of that has to survive the next sync.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Availability, Event, EventSource, EventType, Period, PeriodKind,
)
from app.schedule import build_plan, shapes_the_day


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


MONDAY = utc(2026, 8, 10, 8)
FORTNIGHT = MONDAY + timedelta(days=14)


def create(client, **overrides):
    payload = {
        "title": "Thing",
        "event_type": "one_time",
        "starts_at": "2026-08-10T10:00:00Z",
        "ends_at": "2026-08-10T11:00:00Z",
    }
    payload.update(overrides)
    return client.post("/api/events", json=payload)


# --- Creating (#14) -----------------------------------------------------

def test_creating_a_one_time_event(client, db_session):
    response = create(client, title="Coffee with Sam")

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "manual"
    assert body["availability"] == "busy"
    # Nothing guessed it, so a sync has nothing to overwrite.
    assert body["type_locked"] is True
    assert db_session.query(Event).count() == 1


def test_creating_a_deadline(client):
    response = create(client, title="Essay", event_type="deadline",
                      starts_at=None, ends_at=None,
                      due_at="2026-08-14T23:59:00Z",
                      expected_prep_minutes=120)

    assert response.status_code == 201
    body = response.json()
    assert body["event_type"] == "deadline"
    assert body["expected_prep_minutes"] == 120


def test_creating_a_work_window(client):
    response = create(client, title="At work", availability="work_window",
                      starts_at="2026-08-10T09:00:00Z",
                      ends_at="2026-08-10T17:00:00Z")
    assert response.json()["availability"] == "work_window"


@pytest.mark.parametrize("payload, reason", [
    ({"event_type": "deadline", "starts_at": None, "ends_at": None},
     "deadline with no due date"),
    ({"event_type": "deadline", "due_at": "2026-08-14T23:59:00Z"},
     "deadline that also carries a span"),
    ({"starts_at": None, "ends_at": None}, "event with no times"),
    ({"ends_at": "2026-08-10T09:00:00Z"}, "event ending before it starts"),
    ({"due_at": "2026-08-14T23:59:00Z"}, "one_time event with a due date"),
])
def test_impossible_shapes_are_refused_with_an_explanation(client, payload, reason):
    """The CHECK constraint would catch these, but as a 500 with a traceback."""
    response = create(client, **payload)
    assert response.status_code == 422, reason
    assert response.json()["detail"]


def test_prep_must_be_positive(client):
    assert create(client, expected_prep_minutes=0).status_code == 422


# --- Editing (#13) ------------------------------------------------------

def test_correcting_an_event_into_a_deadline(client, db_session):
    """The core of #13: a calendar entry that is really a due date."""
    event_id = create(client, title="Module 3 Quiz").json()["id"]

    response = client.patch(f"/api/events/{event_id}", json={
        "event_type": "deadline",
        "due_at": "2026-08-14T23:59:00Z",
        "expected_prep_minutes": 90,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "deadline"
    # The old shape's columns cannot survive the switch.
    assert body["starts_at"] is None and body["ends_at"] is None
    assert body["due_at"] is not None


def test_correcting_a_deadline_back_into_an_event(client):
    event_id = create(client, event_type="deadline", starts_at=None,
                      ends_at=None, due_at="2026-08-14T23:59:00Z").json()["id"]

    response = client.patch(f"/api/events/{event_id}", json={
        "event_type": "one_time",
        "starts_at": "2026-08-14T09:00:00Z",
        "ends_at": "2026-08-14T10:00:00Z",
    })

    assert response.status_code == 200
    assert response.json()["due_at"] is None


def test_changing_type_without_the_matching_times_is_refused(client):
    event_id = create(client).json()["id"]
    response = client.patch(f"/api/events/{event_id}",
                            json={"event_type": "deadline"})
    assert response.status_code == 422


def test_editing_the_title_alone_leaves_the_times_alone(client):
    event_id = create(client).json()["id"]
    response = client.patch(f"/api/events/{event_id}", json={"title": "Renamed"})

    body = response.json()
    assert body["title"] == "Renamed"
    assert body["starts_at"] is not None


def test_correcting_the_classification_locks_it(client, db_session):
    """So the next sync does not overwrite the user's judgement."""
    event = Event(
        user_id=1, title="At work", event_type=EventType.ONE_TIME,
        source=EventSource.IMPORTED, availability=Availability.BUSY,
        starts_at=utc(2026, 8, 10, 9), ends_at=utc(2026, 8, 10, 17),
    )
    db_session.add(event)
    db_session.commit()

    response = client.patch(f"/api/events/{event.id}",
                            json={"availability": "work_window"})

    assert response.json()["type_locked"] is True


def test_editing_only_the_title_does_not_lock_the_classification(
    client, db_session
):
    """Renaming is not a judgement about what the event *is*."""
    event = Event(
        user_id=1, title="Standup", event_type=EventType.ONE_TIME,
        source=EventSource.IMPORTED, starts_at=utc(2026, 8, 10, 9),
        ends_at=utc(2026, 8, 10, 10),
    )
    db_session.add(event)
    db_session.commit()

    client.patch(f"/api/events/{event.id}", json={"title": "Team sync"})

    assert db_session.query(Event).one().type_locked is False


def test_a_user_can_hand_an_event_back_to_inference(client, db_session):
    event_id = create(client).json()["id"]
    assert client.get(f"/api/events/{event_id}").json()["type_locked"] is True

    response = client.patch(f"/api/events/{event_id}",
                            json={"type_locked": False})
    assert response.json()["type_locked"] is False


# --- Deleting -----------------------------------------------------------

def test_deleting_a_manual_event(client, db_session):
    event_id = create(client).json()["id"]
    assert client.delete(f"/api/events/{event_id}").status_code == 204
    assert db_session.query(Event).count() == 0


def test_an_imported_event_cannot_be_deleted(client, db_session):
    """It would simply come back on the next sync, which reads as a bug."""
    event = Event(
        user_id=1, title="Imported", event_type=EventType.ONE_TIME,
        source=EventSource.IMPORTED, starts_at=utc(2026, 8, 10, 9),
        ends_at=utc(2026, 8, 10, 10),
    )
    db_session.add(event)
    db_session.commit()

    response = client.delete(f"/api/events/{event.id}")

    assert response.status_code == 409
    assert "free" in response.json()["detail"]


# --- Ownership ----------------------------------------------------------

def test_another_users_event_is_not_reachable(client, db_session):
    from app.models import User

    other = User(email="other@example.com")
    db_session.add(other)
    db_session.commit()
    event = Event(
        user_id=other.id, title="Theirs", event_type=EventType.ONE_TIME,
        source=EventSource.MANUAL, starts_at=utc(2026, 8, 10, 9),
        ends_at=utc(2026, 8, 10, 10),
    )
    db_session.add(event)
    db_session.commit()

    assert client.get(f"/api/events/{event.id}").status_code == 404
    assert client.patch(f"/api/events/{event.id}",
                        json={"title": "Mine"}).status_code == 404
    assert client.delete(f"/api/events/{event.id}").status_code == 404


# --- What each view shows -----------------------------------------------

def _event(user, **kwargs):
    base = dict(
        user_id=user.id, title="Thing", event_type=EventType.ONE_TIME,
        source=EventSource.IMPORTED, starts_at=utc(2026, 8, 10, 10),
        ends_at=utc(2026, 8, 10, 11),
    )
    base.update(kwargs)
    return Event(**base)


def test_the_generated_view_keeps_commitments_and_deadlines(user):
    """A meeting still has to be seen, whatever calendar it came from."""
    meeting = _event(user, availability=Availability.BUSY)
    shift = _event(user, availability=Availability.WORK_WINDOW)
    deadline = _event(user, event_type=EventType.DEADLINE, starts_at=None,
                      ends_at=None, due_at=utc(2026, 8, 14, 17))

    assert shapes_the_day(meeting)
    assert shapes_the_day(shift)
    assert shapes_the_day(deadline)


def test_the_generated_view_drops_informational_clutter(user):
    """The all-day markers that would otherwise bury the schedule."""
    marker = _event(user, availability=Availability.FREE, is_all_day=True)
    assert not shapes_the_day(marker)


def test_the_generated_view_filters_the_feed(client, db_session, user):
    db_session.add_all([
        _event(user, title="Standup", availability=Availability.BUSY),
        _event(user, title="Reading day", availability=Availability.FREE,
               is_all_day=True),
    ])
    db_session.commit()

    params = {"start": "2026-08-10T00:00:00Z", "end": "2026-08-11T00:00:00Z"}
    generated = client.get("/api/schedule", params=params).json()
    calendar = client.get(
        "/api/schedule", params={**params, "view": "calendar"}).json()

    assert generated["view"] == "generated"
    assert [e["title"] for e in generated["events"]] == ["Standup"]
    # The raw diary keeps everything.
    assert len(calendar["events"]) == 2


def test_periods_appear_only_in_the_generated_view(client, db_session, user):
    """The views are alternatives, not overlapping copies of each other."""
    db_session.add(Period(
        user_id=user.id, starts_at=utc(2026, 8, 10, 9),
        ends_at=utc(2026, 8, 10, 10)))
    db_session.commit()

    params = {"start": "2026-08-10T00:00:00Z", "end": "2026-08-11T00:00:00Z"}
    generated = client.get("/api/schedule", params=params).json()
    calendar = client.get(
        "/api/schedule", params={**params, "view": "calendar"}).json()

    assert len(generated["periods"]) == 1
    assert calendar["periods"] == []


def test_a_commitment_appears_in_both_views(client, db_session, user):
    """The one deliberate overlap: a meeting matters either way."""
    db_session.add(_event(user, title="Standup", availability=Availability.BUSY))
    db_session.commit()

    params = {"start": "2026-08-10T00:00:00Z", "end": "2026-08-11T00:00:00Z"}
    for view in ("generated", "calendar"):
        body = client.get("/api/schedule", params={**params, "view": view}).json()
        assert "Standup" in [e["title"] for e in body["events"]], view


def test_the_calendar_view_draws_no_horizon(client):
    """Nothing is settled there, because nothing generated is shown."""
    params = {"start": "2026-08-10T00:00:00Z", "end": "2026-08-11T00:00:00Z"}

    assert client.get("/api/schedule", params=params).json()[
        "horizon_ends_at"] is not None
    assert client.get("/api/schedule", params={
        **params, "view": "calendar"}).json()["horizon_ends_at"] is None


def test_an_unknown_view_is_rejected(client):
    response = client.get("/api/schedule", params={
        "start": "2026-08-10T00:00:00Z", "end": "2026-08-11T00:00:00Z",
        "view": "gantt"})
    assert response.status_code == 422


# --- Work windows drive generation --------------------------------------

def test_periods_are_generated_inside_a_work_window(db_session, user):
    """The scenario that prompted all this: a shift is where work happens."""
    user.workdays = []  # No normal working hours at all, so only the shift.
    db_session.add_all([
        _event(user, title="At work", availability=Availability.WORK_WINDOW,
               starts_at=utc(2026, 8, 10, 9), ends_at=utc(2026, 8, 10, 17)),
        _event(user, title="Report", event_type=EventType.DEADLINE,
               starts_at=None, ends_at=None, due_at=utc(2026, 8, 14, 17),
               expected_prep_minutes=100),
    ])
    db_session.commit()

    plan = build_plan(db_session, user, MONDAY, FORTNIGHT, MONDAY,
                      respect_horizon=False)

    assert len(plan.new_periods) == 2
    for period in plan.periods:
        assert utc(2026, 8, 10, 9) <= period.starts_at < utc(2026, 8, 10, 17)


def test_a_busy_block_still_prevents_periods(db_session, user):
    """The contrast: the same span marked busy generates nothing."""
    user.workdays = []
    db_session.add_all([
        _event(user, title="At work", availability=Availability.BUSY,
               starts_at=utc(2026, 8, 10, 9), ends_at=utc(2026, 8, 10, 17)),
        _event(user, title="Report", event_type=EventType.DEADLINE,
               starts_at=None, ends_at=None, due_at=utc(2026, 8, 14, 17),
               expected_prep_minutes=100),
    ])
    db_session.commit()

    plan = build_plan(db_session, user, MONDAY, FORTNIGHT, MONDAY,
                      respect_horizon=False)

    assert plan.new_periods == ()
    assert plan.unmet


def test_a_meeting_inside_a_work_window_is_still_avoided(db_session, user):
    """Being at work does not mean being free during the 11am meeting."""
    user.workdays = []
    db_session.add_all([
        _event(user, title="At work", availability=Availability.WORK_WINDOW,
               starts_at=utc(2026, 8, 10, 9), ends_at=utc(2026, 8, 10, 17)),
        _event(user, title="All-hands", availability=Availability.BUSY,
               starts_at=utc(2026, 8, 10, 9), ends_at=utc(2026, 8, 10, 16)),
        _event(user, title="Report", event_type=EventType.DEADLINE,
               starts_at=None, ends_at=None, due_at=utc(2026, 8, 14, 17),
               expected_prep_minutes=50),
    ])
    db_session.commit()

    plan = build_plan(db_session, user, MONDAY, FORTNIGHT, MONDAY,
                      respect_horizon=False)

    assert len(plan.new_periods) == 1
    assert plan.periods[0].starts_at == utc(2026, 8, 10, 16)


def test_a_free_event_neither_blocks_nor_offers(db_session, user):
    user.workdays = []
    db_session.add_all([
        _event(user, title="Reminder", availability=Availability.FREE,
               starts_at=utc(2026, 8, 10, 9), ends_at=utc(2026, 8, 10, 17)),
        _event(user, title="Report", event_type=EventType.DEADLINE,
               starts_at=None, ends_at=None, due_at=utc(2026, 8, 14, 17),
               expected_prep_minutes=50),
    ])
    db_session.commit()

    plan = build_plan(db_session, user, MONDAY, FORTNIGHT, MONDAY,
                      respect_horizon=False)

    # No working hours and no window, so nothing is offered.
    assert plan.new_periods == ()


def test_generating_after_creating_a_deadline_produces_periods(
    client, db_session, user
):
    """End to end: the flow a user actually takes in #14."""
    due = datetime.now(timezone.utc) + timedelta(days=10)
    create(client, title="Essay", event_type="deadline", starts_at=None,
           ends_at=None, due_at=due.isoformat(), expected_prep_minutes=100)

    response = client.post("/api/schedule/generate", json={})

    assert response.json()["committed"] is True
    assert db_session.query(Period).filter(
        Period.kind == PeriodKind.WORK).count() == 2
