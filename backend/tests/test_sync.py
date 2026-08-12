"""Tests for importing Google Calendar events.

Google's payloads are plain dicts, so the mapping is tested directly with the
shapes the API actually returns — including the two-form start/end (`dateTime`
for timed events, `date` for all-day ones) that drives deadline inference, and
the calendarList entries that decide which calendars are imported at all.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.integrations.google_calendar import SyncTokenExpired
from app.models import (
    Calendar, CalendarConnection, CalendarKind, Event, EventSource, EventType,
)
from app.integrations.sync import (
    apply_events, clear_calendar, deadline_moment, discover_calendars,
    sync_calendar, sync_connection,
)

UTC = ZoneInfo("UTC")


def timed(event_id, summary, start, end):
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }


def all_day(event_id, summary, day, end_day=None):
    """Google's all-day end date is exclusive, so a one-day event ends on the
    following date. Defaulted that way here to match the real API."""
    if end_day is None:
        end_day = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": summary,
        "start": {"date": day},
        "end": {"date": end_day},
    }


def listing(calendar_id, summary, *, primary=False, selected=True, **extra):
    """One entry as it appears in Google's calendarList response."""
    return {
        "id": calendar_id,
        "summary": summary,
        "primary": primary,
        "selected": selected,
        "backgroundColor": "#3f51b5",
        **extra,
    }


@pytest.fixture
def connection(db_session, user):
    record = CalendarConnection(
        user_id=user.id, provider="google", provider_account_id="sub-1",
        account_email="owner@example.com", default_kind=CalendarKind.SCHOOL,
        access_token="access", refresh_token="refresh", scopes="",
    )
    db_session.add(record)
    db_session.commit()
    return record


@pytest.fixture
def calendar(db_session, connection):
    record = Calendar(
        calendar_connection_id=connection.id,
        provider_calendar_id="owner@example.com",
        name="Primary", is_primary=True, selected=True,
        kind=CalendarKind.SCHOOL,
    )
    db_session.add(record)
    db_session.commit()
    return record


def apply(db_session, calendar, payloads):
    result = apply_events(db_session, calendar, payloads, UTC)
    db_session.commit()
    return result


# --- Discovering the calendars in an account ----------------------------

def test_discovery_creates_a_row_per_calendar(db_session, connection):
    with patch("app.integrations.google_calendar.fetch_calendar_list", return_value=[
        listing("owner@example.com", "Personal", primary=True),
        listing("work@group.calendar.google.com", "Work"),
        listing("cs406@group.calendar.google.com", "CS406"),
    ]):
        calendars = discover_calendars(db_session, connection, "access")

    assert len(calendars) == 3
    assert {c.name for c in calendars} == {"Personal", "Work", "CS406"}
    assert sum(c.is_primary for c in calendars) == 1


def test_new_calendars_inherit_the_accounts_default_kind(db_session, connection):
    with patch("app.integrations.google_calendar.fetch_calendar_list",
               return_value=[listing("a", "A")]):
        calendars = discover_calendars(db_session, connection, "access")

    assert calendars[0].kind == CalendarKind.SCHOOL  # connection default


def test_googles_own_checkbox_seeds_selection(db_session, connection):
    """What the user already curates in Google is the sensible starting point."""
    with patch("app.integrations.google_calendar.fetch_calendar_list", return_value=[
        listing("a", "Shown", selected=True),
        listing("b", "Hidden", selected=False),
    ]):
        calendars = {c.name: c for c in discover_calendars(
            db_session, connection, "access")}

    assert calendars["Shown"].selected is True
    assert calendars["Hidden"].selected is False


def test_the_primary_calendar_is_always_selected(db_session, connection):
    with patch("app.integrations.google_calendar.fetch_calendar_list", return_value=[
        listing("a", "Primary", primary=True, selected=False),
    ]):
        calendars = discover_calendars(db_session, connection, "access")
    assert calendars[0].selected is True


def test_rediscovery_updates_presentation_but_keeps_the_users_choices(
    db_session, connection
):
    """Renaming a calendar in Google must not silently re-tick it."""
    with patch("app.integrations.google_calendar.fetch_calendar_list",
               return_value=[listing("a", "Old name")]):
        discover_calendars(db_session, connection, "access")

    calendar = connection.calendars[0]
    calendar.selected = False
    calendar.kind = CalendarKind.WORK
    db_session.commit()

    with patch("app.integrations.google_calendar.fetch_calendar_list", return_value=[
        listing("a", "New name", backgroundColor="#009688"),
    ]):
        discover_calendars(db_session, connection, "access")

    assert len(connection.calendars) == 1
    calendar = connection.calendars[0]
    assert calendar.name == "New name"
    assert calendar.color == "#009688"
    assert calendar.selected is False
    assert calendar.kind == CalendarKind.WORK


def test_summary_override_wins_over_summary(db_session, connection):
    """It is the name the user gave the calendar themselves."""
    with patch("app.integrations.google_calendar.fetch_calendar_list", return_value=[
        listing("a", "Shared roster", summaryOverride="My shifts"),
    ]):
        calendars = discover_calendars(db_session, connection, "access")
    assert calendars[0].name == "My shifts"


# --- Mapping ------------------------------------------------------------

def test_a_timed_event_becomes_committed_time(db_session, calendar):
    apply(db_session, calendar, [
        timed("e1", "CS406 Lecture", "2026-08-10T10:00:00Z",
              "2026-08-10T11:30:00Z"),
    ])

    event = db_session.query(Event).one()
    assert event.event_type == EventType.ONE_TIME
    assert event.source == EventSource.IMPORTED
    assert event.calendar_id == calendar.id
    assert event.provider_event_id == "e1"
    assert event.is_all_day is False
    assert event.due_at is None


def test_an_all_day_assignment_becomes_a_deadline(db_session, calendar):
    apply(db_session, calendar, [all_day("e1", "Essay 2 due", "2026-08-14")])

    event = db_session.query(Event).one()
    assert event.event_type == EventType.DEADLINE
    assert event.expected_prep_minutes
    # The CHECK constraint requires a deadline to carry no span.
    assert event.starts_at is None and event.ends_at is None
    assert event.due_at is not None


def test_an_all_day_non_assignment_keeps_its_span(db_session, calendar):
    apply(db_session, calendar, [
        all_day("e1", "Department retreat", "2026-08-14", "2026-08-15"),
    ])

    event = db_session.query(Event).one()
    assert event.event_type == EventType.ONE_TIME
    assert event.is_all_day is True
    assert event.starts_at is not None and event.ends_at is not None
    assert event.due_at is None


def test_a_deadline_is_due_at_the_end_of_its_day(db_session, calendar):
    """"Due Friday" means by the end of Friday, not the start of it."""
    apply(db_session, calendar, [all_day("e1", "Essay due", "2026-08-14")])

    due = db_session.query(Event).one().due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    assert due.date().isoformat() == "2026-08-14"
    assert due.hour == 23


def test_deadline_moment_follows_the_users_timezone():
    """End of Friday in Los Angeles is not end of Friday in UTC."""
    la = deadline_moment(date(2026, 8, 14), ZoneInfo("America/Los_Angeles"))
    assert la == datetime(2026, 8, 15, 6, 59, tzinfo=timezone.utc)


def test_an_event_with_no_usable_time_is_skipped(db_session, calendar):
    apply(db_session, calendar, [
        {"id": "e1", "status": "confirmed", "summary": "Nothing",
         "start": {}, "end": {}},
    ])
    assert db_session.query(Event).count() == 0


def test_a_missing_title_does_not_break_the_import(db_session, calendar):
    apply(db_session, calendar, [
        {"id": "e1", "status": "confirmed",
         "start": {"dateTime": "2026-08-10T10:00:00Z"},
         "end": {"dateTime": "2026-08-10T11:00:00Z"}},
    ])
    assert db_session.query(Event).one().title == "(untitled)"


# --- Per-calendar kind --------------------------------------------------

def test_kind_is_read_from_the_calendar_not_the_account(db_session, calendar):
    """The whole point of moving it: one account, two kinds of calendar."""
    calendar.kind = CalendarKind.PERSONAL
    db_session.commit()

    apply(db_session, calendar, [all_day("e1", "Essay 2 due", "2026-08-14")])

    assert db_session.query(Event).one().event_type == EventType.ONE_TIME


def test_two_calendars_on_one_account_infer_differently(db_session, connection):
    school = Calendar(calendar_connection_id=connection.id,
                      provider_calendar_id="school", name="CS406",
                      kind=CalendarKind.SCHOOL)
    personal = Calendar(calendar_connection_id=connection.id,
                        provider_calendar_id="personal", name="Personal",
                        kind=CalendarKind.PERSONAL)
    db_session.add_all([school, personal])
    db_session.commit()

    apply(db_session, school, [all_day("a", "Essay 2 due", "2026-08-14")])
    apply(db_session, personal, [all_day("b", "Essay 2 due", "2026-08-14")])

    types = {e.calendar_id: e.event_type for e in db_session.query(Event)}
    assert types[school.id] == EventType.DEADLINE
    assert types[personal.id] == EventType.ONE_TIME


def test_the_same_provider_event_id_can_exist_on_two_calendars(
    db_session, connection
):
    """Google ids are unique per calendar, not per account."""
    first = Calendar(calendar_connection_id=connection.id,
                     provider_calendar_id="one", name="One")
    second = Calendar(calendar_connection_id=connection.id,
                      provider_calendar_id="two", name="Two")
    db_session.add_all([first, second])
    db_session.commit()

    shared = timed("shared-id", "Shared",
                   "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
    apply(db_session, first, [shared])
    apply(db_session, second, [shared])

    assert db_session.query(Event).count() == 2


# --- Recurrence ---------------------------------------------------------

def test_recurring_instances_are_stored_separately(db_session, calendar):
    """singleEvents=true expands a series, so each instance has its own id."""
    apply(db_session, calendar, [
        timed("e1_20260810", "CS406 Lecture",
              "2026-08-10T10:00:00Z", "2026-08-10T11:30:00Z"),
        timed("e1_20260812", "CS406 Lecture",
              "2026-08-12T10:00:00Z", "2026-08-12T11:30:00Z"),
    ])
    assert db_session.query(Event).count() == 2


# --- De-duplication and updates -----------------------------------------

def test_re_importing_updates_rather_than_duplicates(db_session, calendar):
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z"),
    ])
    result = apply(db_session, calendar, [
        timed("e1", "Standup (moved)", "2026-08-10T09:30:00Z",
              "2026-08-10T09:45:00Z"),
    ])

    event = db_session.query(Event).one()
    assert event.title == "Standup (moved)"
    assert result.updated == 1 and result.created == 0


def test_a_cancelled_event_is_removed(db_session, calendar):
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z"),
    ])
    result = apply(db_session, calendar, [{"id": "e1", "status": "cancelled"}])

    assert db_session.query(Event).count() == 0
    assert result.deleted == 1


def test_cancelling_an_unknown_event_is_harmless(db_session, calendar):
    result = apply(db_session, calendar, [
        {"id": "never-seen", "status": "cancelled"}])
    assert result.deleted == 0


def test_an_event_without_an_id_is_ignored(db_session, calendar):
    apply(db_session, calendar, [
        {"status": "confirmed", "summary": "No id",
         "start": {"dateTime": "2026-08-10T10:00:00Z"},
         "end": {"dateTime": "2026-08-10T11:00:00Z"}},
    ])
    assert db_session.query(Event).count() == 0


# --- Respecting the user's corrections ----------------------------------

def test_a_locked_event_keeps_its_type_through_a_resync(db_session, calendar):
    """The whole point of type_locked: a correction outranks a guess."""
    apply(db_session, calendar, [
        all_day("e1", "Department retreat", "2026-08-14", "2026-08-15")])

    event = db_session.query(Event).one()
    assert event.event_type == EventType.ONE_TIME
    event.event_type = EventType.DEADLINE
    event.starts_at = event.ends_at = None
    event.due_at = datetime(2026, 8, 14, 23, 59, tzinfo=timezone.utc)
    event.expected_prep_minutes = 240
    event.type_locked = True
    db_session.commit()

    apply(db_session, calendar, [
        all_day("e1", "Department retreat", "2026-08-14", "2026-08-15")])

    event = db_session.query(Event).one()
    assert event.event_type == EventType.DEADLINE
    assert event.expected_prep_minutes == 240


def test_a_locked_event_still_tracks_title_changes(db_session, calendar):
    """Locking the type must not freeze the event's wording as well."""
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z")])
    db_session.query(Event).one().type_locked = True
    db_session.commit()

    apply(db_session, calendar, [
        timed("e1", "Team sync", "2026-08-10T09:00:00Z",
              "2026-08-10T09:15:00Z")])

    assert db_session.query(Event).one().title == "Team sync"


def test_an_unlocked_event_is_reclassified_on_resync(db_session, calendar):
    """So keyword-table improvements reach events already imported."""
    apply(db_session, calendar, [all_day("e1", "Untitled block", "2026-08-14")])
    assert db_session.query(Event).one().event_type == EventType.ONE_TIME

    apply(db_session, calendar, [all_day("e1", "Essay due", "2026-08-14")])
    assert db_session.query(Event).one().event_type == EventType.DEADLINE


# --- Sync tokens, per calendar ------------------------------------------

def test_first_sync_stores_the_token_on_the_calendar(db_session, calendar):
    with patch("app.integrations.google_calendar.fetch_all",
               return_value=([], "sync-token-1")) as fetch:
        result = sync_calendar(db_session, calendar, "access",
                               now=datetime.now(timezone.utc))

    assert calendar.sync_token == "sync-token-1"
    assert calendar.last_synced_at is not None
    assert result.full_resync is True
    # No stored token, so it must be a windowed import.
    assert fetch.call_args.kwargs.get("sync_token") is None
    assert fetch.call_args.kwargs.get("time_min") is not None
    # And it must ask for this calendar, not "primary".
    assert fetch.call_args.args[1] == "owner@example.com"


def test_a_later_sync_is_incremental(db_session, calendar):
    calendar.sync_token = "sync-token-1"
    db_session.commit()

    with patch("app.integrations.google_calendar.fetch_all",
               return_value=([], "sync-token-2")) as fetch:
        result = sync_calendar(db_session, calendar, "access",
                               now=datetime.now(timezone.utc))

    assert fetch.call_args.kwargs["sync_token"] == "sync-token-1"
    assert calendar.sync_token == "sync-token-2"
    assert result.full_resync is False


def test_an_expired_token_falls_back_to_a_full_import(db_session, calendar):
    """Google invalidates sync tokens after about a week; a 410 is routine."""
    calendar.sync_token = "stale"
    db_session.commit()

    with patch("app.integrations.google_calendar.fetch_all",
               side_effect=[SyncTokenExpired(), ([], "fresh")]) as fetch:
        result = sync_calendar(db_session, calendar, "access",
                               now=datetime.now(timezone.utc))

    assert result.full_resync is True
    assert calendar.sync_token == "fresh"
    assert fetch.call_count == 2
    assert fetch.call_args.kwargs.get("sync_token") is None


# --- Syncing a whole account --------------------------------------------

def _account_sync(db_session, connection, listings, events=()):
    with (
        patch("app.integrations.sync.get_access_token", return_value="access"),
        patch("app.integrations.google_calendar.fetch_calendar_list", return_value=listings),
        patch("app.integrations.google_calendar.fetch_all",
              return_value=(list(events), "tok")) as fetch,
    ):
        result = sync_connection(db_session, connection)
    return result, fetch


def test_only_selected_calendars_are_imported(db_session, connection):
    result, fetch = _account_sync(db_session, connection, [
        listing("a", "Kept", selected=True),
        listing("b", "Skipped", selected=False),
    ], events=[timed("e1", "Thing", "2026-08-10T10:00:00Z",
                     "2026-08-10T11:00:00Z")])

    assert fetch.call_count == 1
    assert [c.args[1] for c in fetch.call_args_list] == ["a"]
    assert result.created == 1


def test_every_selected_calendar_is_imported(db_session, connection):
    _, fetch = _account_sync(db_session, connection, [
        listing("a", "One"), listing("b", "Two"), listing("c", "Three"),
    ])
    assert sorted(c.args[1] for c in fetch.call_args_list) == ["a", "b", "c"]


def test_one_failing_calendar_does_not_abandon_the_others(db_session, connection):
    """A single broken calendar should not cost the user every other import."""
    with (
        patch("app.integrations.sync.get_access_token", return_value="access"),
        patch("app.integrations.google_calendar.fetch_calendar_list", return_value=[
            listing("bad", "Broken"), listing("good", "Fine"),
        ]),
        patch("app.integrations.google_calendar.fetch_all", side_effect=[
            RuntimeError("boom"),
            ([timed("e1", "Thing", "2026-08-10T10:00:00Z",
                    "2026-08-10T11:00:00Z")], "tok"),
        ]),
    ):
        result = sync_connection(db_session, connection)

    assert result.created == 1
    by_name = {c.name: c for c in connection.calendars}
    assert "boom" in by_name["Broken"].last_sync_error
    assert by_name["Fine"].last_sync_error is None
    assert connection.last_sync_error  # rolled up for the account


def test_a_successful_sync_clears_a_previous_error(db_session, connection):
    connection.last_sync_error = "1 calendar(s) could not be imported"
    db_session.commit()

    _account_sync(db_session, connection, [listing("a", "Fine")])

    assert connection.last_sync_error is None


# --- Unselecting --------------------------------------------------------

def test_clearing_a_calendar_removes_its_events(db_session, calendar):
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z"),
        timed("e2", "Retro", "2026-08-10T11:00:00Z", "2026-08-10T12:00:00Z"),
    ])
    calendar.sync_token = "tok"
    db_session.commit()

    removed = clear_calendar(db_session, calendar)

    assert removed == 2
    assert db_session.query(Event).count() == 0
    # Cleared so re-selecting does a fresh full import rather than an
    # incremental one that would return nothing.
    assert calendar.sync_token is None


def test_clearing_one_calendar_leaves_the_others_alone(db_session, connection):
    keep = Calendar(calendar_connection_id=connection.id,
                    provider_calendar_id="keep", name="Keep")
    drop = Calendar(calendar_connection_id=connection.id,
                    provider_calendar_id="drop", name="Drop")
    db_session.add_all([keep, drop])
    db_session.commit()

    event = timed("e1", "Thing", "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
    apply(db_session, keep, [event])
    apply(db_session, drop, [event])

    clear_calendar(db_session, drop)

    remaining = db_session.query(Event).all()
    assert len(remaining) == 1
    assert remaining[0].calendar_id == keep.id


def test_deleting_a_calendar_cascades_to_its_events(db_session, calendar):
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z")])

    db_session.delete(calendar)
    db_session.commit()

    assert db_session.query(Event).count() == 0


def test_disconnecting_an_account_cascades_through_calendars(
    db_session, connection, calendar
):
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z")])

    db_session.delete(connection)
    db_session.commit()

    assert db_session.query(Calendar).count() == 0
    assert db_session.query(Event).count() == 0


# --- Endpoints ----------------------------------------------------------

def test_listing_nests_calendars_under_their_account(client, db_session,
                                                     connection):
    db_session.add_all([
        Calendar(calendar_connection_id=connection.id, provider_calendar_id="b",
                 name="Work", kind=CalendarKind.WORK),
        Calendar(calendar_connection_id=connection.id, provider_calendar_id="a",
                 name="Personal", is_primary=True),
    ])
    db_session.commit()

    body = client.get("/api/calendars").json()
    calendars = body["connections"][0]["calendars"]

    assert [c["name"] for c in calendars] == ["Personal", "Work"]  # primary first
    assert calendars[1]["kind"] == "work"


def test_unticking_a_calendar_removes_its_events(client, db_session,
                                                 connection, calendar):
    apply(db_session, calendar, [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z")])

    response = client.patch(
        f"/api/calendars/{connection.id}/calendars/{calendar.id}",
        json={"selected": False})

    assert response.status_code == 200
    assert response.json()["events_removed"] == 1
    assert response.json()["calendar"]["selected"] is False
    assert db_session.query(Event).count() == 0


def test_ticking_a_calendar_imports_immediately(client, db_session,
                                                connection, calendar):
    calendar.selected = False
    db_session.commit()

    with (
        patch("app.api.calendars.get_access_token", return_value="access"),
        patch("app.integrations.google_calendar.fetch_all", return_value=(
            [timed("e1", "Standup", "2026-08-10T09:00:00Z",
                   "2026-08-10T09:15:00Z")], "tok")),
    ):
        response = client.patch(
            f"/api/calendars/{connection.id}/calendars/{calendar.id}",
            json={"selected": True})

    assert response.json()["events_imported"] == 1
    assert db_session.query(Event).count() == 1


def test_changing_kind_reclassifies_existing_events(client, db_session,
                                                    connection, calendar):
    """Switching a calendar to school must re-read what is already imported."""
    calendar.kind = CalendarKind.PERSONAL
    db_session.commit()
    apply(db_session, calendar, [all_day("e1", "Essay 2 due", "2026-08-14")])
    assert db_session.query(Event).one().event_type == EventType.ONE_TIME

    with (
        patch("app.api.calendars.get_access_token", return_value="access"),
        patch("app.integrations.google_calendar.fetch_all",
              return_value=([all_day("e1", "Essay 2 due", "2026-08-14")], "tok")),
    ):
        client.patch(f"/api/calendars/{connection.id}/calendars/{calendar.id}",
                     json={"kind": "school"})

    assert db_session.query(Event).one().event_type == EventType.DEADLINE


def test_updating_an_unknown_calendar_is_a_404(client, connection):
    assert client.patch(
        f"/api/calendars/{connection.id}/calendars/99999",
        json={"selected": False}).status_code == 404


def test_a_calendar_on_someone_elses_account_is_a_404(client, db_session,
                                                      connection, calendar):
    from app.models import User

    other = User(email="other@example.com")
    db_session.add(other)
    db_session.commit()
    connection.user_id = other.id
    db_session.commit()

    assert client.patch(
        f"/api/calendars/{connection.id}/calendars/{calendar.id}",
        json={"selected": False}).status_code == 404


def test_resync_endpoint_reports_what_changed(client, db_session, connection):
    payloads = [
        timed("e1", "Standup", "2026-08-10T09:00:00Z", "2026-08-10T09:15:00Z"),
        all_day("e2", "Essay due", "2026-08-14"),
    ]
    with (
        patch("app.integrations.sync.get_access_token", return_value="access"),
        patch("app.integrations.google_calendar.fetch_calendar_list",
              return_value=[listing("a", "Primary", primary=True)]),
        patch("app.integrations.google_calendar.fetch_all", return_value=(payloads, "tok")),
    ):
        response = client.post(f"/api/calendars/{connection.id}/sync")

    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2
    assert body["connection"]["calendars"][0]["name"] == "Primary"
    assert db_session.query(Event).count() == 2


def test_resync_reports_a_dead_connection(client, db_session, connection):
    from app.integrations.tokens import CalendarReauthRequired

    with patch("app.integrations.sync.get_access_token",
               side_effect=CalendarReauthRequired(connection.id, "revoked")):
        response = client.post(f"/api/calendars/{connection.id}/sync")

    assert response.status_code == 409
    assert connection.last_sync_error


def test_resync_requires_ownership(client, db_session, connection):
    from app.models import User

    other = User(email="other@example.com")
    db_session.add(other)
    db_session.commit()
    connection.user_id = other.id
    db_session.commit()

    assert client.post(
        f"/api/calendars/{connection.id}/sync").status_code == 404


def test_a_failed_first_import_is_recorded_not_raised(db_session, connection):
    """Connecting succeeded; only the import failed, so it must not error out."""
    from app.integrations.sync import sync_quietly

    with patch("app.integrations.sync.get_access_token", side_effect=RuntimeError("boom")):
        sync_quietly(db_session, connection)

    assert "boom" in connection.last_sync_error
