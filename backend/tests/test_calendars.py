"""Tests for connecting and managing calendar accounts (issue #7).

The consent handshake itself belongs to Google, so what is tested here is
everything on our side of it: that the callback stores what it should, that it
refuses a consent missing the calendar scope, and that connections are scoped
to their owner.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.calendar_tokens import GOOGLE_CALENDAR_SCOPE
from app.models import (
    Calendar, CalendarConnection, CalendarKind, Event, EventSource, EventType,
    User,
)


def token_response(scope=None, refresh="refresh-token", sub="google-sub-1"):
    """A plausible Google token response, shaped like authlib returns it."""
    return {
        "access_token": "access-token",
        "refresh_token": refresh,
        "expires_in": 3599,
        "scope": scope if scope is not None else f"openid email {GOOGLE_CALENDAR_SCOPE}",
        "userinfo": {"sub": sub, "email": "calendar-owner@example.com"},
    }


@pytest.fixture
def callback(client):
    """Drives the OAuth callback with a canned token response.

    The initial import that connecting triggers is stubbed out here; it has its
    own tests in test_sync.py.
    """
    def run(token=None, kind=None):
        if kind:
            # Stand in for the connect step, which stashes the chosen kind.
            with client as c:
                c.get("/api/calendars/google/connect", params={"kind": kind},
                      follow_redirects=False)
        with (
            patch("app.calendars.oauth.google_calendar.authorize_access_token",
                  return_value=token or token_response()),
            patch("app.calendars.sync_quietly") as imported,
        ):
            response = client.get("/api/calendars/google/callback",
                                  follow_redirects=False)
            response.imported = imported
            return response
    return run


# --- The callback -------------------------------------------------------

def test_callback_stores_the_connection(callback, db_session, user):
    response = callback()

    assert response.status_code == 307
    assert "calendar_connected=1" in response.headers["location"]
    # The calendar list lives on the settings page, so the outcome has to land
    # there or the user never sees the message.
    assert "/settings?" in response.headers["location"]

    connection = db_session.query(CalendarConnection).one()
    assert connection.user_id == user.id
    assert connection.provider == "google"
    assert connection.provider_account_id == "google-sub-1"
    assert connection.account_email == "calendar-owner@example.com"


def test_connecting_imports_events_immediately(callback):
    """A calendar that shows nothing until you find a sync button does not
    look connected."""
    assert callback().imported.called


def test_tokens_are_stored_and_readable(callback, db_session):
    """Encrypted at rest, but the ORM must hand them back usable."""
    callback()

    connection = db_session.query(CalendarConnection).one()
    assert connection.access_token == "access-token"
    assert connection.refresh_token == "refresh-token"
    assert connection.access_token_expires_at is not None
    assert connection.has_scope(GOOGLE_CALENDAR_SCOPE)


def test_expiry_is_recorded_in_the_future(callback, db_session):
    callback()
    connection = db_session.query(CalendarConnection).one()
    expires = connection.access_token_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    assert expires > datetime.now(timezone.utc)


def test_consent_without_the_calendar_scope_is_refused(callback, db_session):
    """Google lets users untick individual permissions on the consent screen."""
    response = callback(token_response(scope="openid email"))

    assert "calendar_error=scope" in response.headers["location"]
    assert db_session.query(CalendarConnection).count() == 0


def test_denied_consent_sends_the_user_back_to_retry(client, db_session):
    with patch("app.calendars.oauth.google_calendar.authorize_access_token",
               side_effect=Exception("access_denied")):
        response = client.get("/api/calendars/google/callback",
                              follow_redirects=False)

    assert "calendar_error=denied" in response.headers["location"]
    assert db_session.query(CalendarConnection).count() == 0


def test_a_response_without_an_identity_is_refused(callback, db_session):
    """No `sub` means no stable id, so two calendars could not be told apart."""
    token = token_response()
    token["userinfo"] = {}
    response = callback(token)

    assert "calendar_error=identity" in response.headers["location"]
    assert db_session.query(CalendarConnection).count() == 0


def test_reconnecting_the_same_account_updates_it(callback, db_session):
    """Not a second row: the unique constraint would reject it anyway."""
    callback()
    db_session.query(CalendarConnection).one().last_sync_error = "expired"
    db_session.commit()

    refreshed = token_response(refresh="new-refresh-token")
    refreshed["access_token"] = "new-access-token"
    callback(refreshed)

    connection = db_session.query(CalendarConnection).one()
    assert connection.access_token == "new-access-token"
    assert connection.refresh_token == "new-refresh-token"
    # Reconnecting is how a user fixes a broken connection, so the error clears.
    assert connection.last_sync_error is None


def test_a_second_google_account_is_a_second_connection(callback, db_session):
    callback()
    callback(token_response(sub="google-sub-2"))
    assert db_session.query(CalendarConnection).count() == 2


def test_refresh_token_is_kept_when_google_omits_it(callback, db_session):
    """Google only returns one on first consent; losing it breaks refresh."""
    callback()
    callback(token_response(refresh=None))

    assert db_session.query(CalendarConnection).one(
    ).refresh_token == "refresh-token"


# --- Calendar kind ------------------------------------------------------

def test_kind_defaults_to_personal(callback, db_session):
    """The conservative default: infer nothing from titles."""
    callback()
    assert db_session.query(CalendarConnection).one(
    ).default_kind == CalendarKind.PERSONAL


def test_kind_chosen_at_connect_time_seeds_the_account(callback, db_session):
    """It is a default for discovered calendars, not the value inference uses;
    that lives on each Calendar so one account can hold both kinds."""
    callback(kind="school")
    assert db_session.query(CalendarConnection).one(
    ).default_kind == CalendarKind.SCHOOL


def test_the_account_default_can_be_changed_later(callback, client, db_session):
    """Only seeds calendars discovered from now on; existing ones keep theirs."""
    callback()
    connection = db_session.query(CalendarConnection).one()

    response = client.patch(f"/api/calendars/{connection.id}",
                            json={"default_kind": "work"})

    assert response.status_code == 200
    assert response.json()["default_kind"] == "work"


def test_an_unknown_kind_is_rejected(callback, client, db_session):
    callback()
    connection = db_session.query(CalendarConnection).one()
    response = client.patch(f"/api/calendars/{connection.id}",
                            json={"default_kind": "holiday"})
    assert response.status_code == 422


# --- Listing and disconnecting ------------------------------------------

def test_listing_reports_connection_state(callback, client):
    callback(kind="school")
    body = client.get("/api/calendars").json()

    assert len(body["connections"]) == 1
    entry = body["connections"][0]
    assert entry["account_email"] == "calendar-owner@example.com"
    assert entry["default_kind"] == "school"
    assert entry["healthy"] is True
    assert entry["last_synced_at"] is None
    # Discovery runs during the import, which this fixture stubs out.
    assert entry["calendars"] == []


def test_a_connection_without_a_refresh_token_reads_as_unhealthy(
    callback, client, db_session
):
    """It cannot survive token expiry, so the UI must prompt a reconnect."""
    callback(token_response(refresh=None))
    body = client.get("/api/calendars").json()
    assert body["connections"][0]["healthy"] is False


def test_disconnecting_removes_the_connection(callback, client, db_session):
    callback()
    connection = db_session.query(CalendarConnection).one()

    with patch("app.calendar_tokens.httpx.post") as revoke:
        response = client.delete(f"/api/calendars/{connection.id}")

    assert response.status_code == 204
    assert db_session.query(CalendarConnection).count() == 0
    # Best effort, but we must actually try to revoke at the provider.
    assert revoke.called


def test_disconnecting_removes_imported_events(callback, client, db_session, user):
    """The CASCADE the schema declares, from account through calendar to event."""
    callback()
    connection = db_session.query(CalendarConnection).one()
    calendar = Calendar(calendar_connection_id=connection.id,
                        provider_calendar_id="primary", name="Primary")
    db_session.add(calendar)
    db_session.commit()
    db_session.add(Event(
        user_id=user.id, title="Imported lecture", event_type=EventType.ONE_TIME,
        source=EventSource.IMPORTED, calendar_id=calendar.id,
        provider_event_id="evt-1",
        starts_at=datetime(2026, 8, 10, 10, tzinfo=timezone.utc),
        ends_at=datetime(2026, 8, 10, 11, tzinfo=timezone.utc),
    ))
    db_session.commit()

    with patch("app.calendar_tokens.httpx.post"):
        client.delete(f"/api/calendars/{connection.id}")

    assert db_session.query(Event).count() == 0


def test_revocation_failure_still_removes_the_connection(
    callback, client, db_session
):
    """A stale grant is better than a connection the user cannot delete."""
    callback()
    connection = db_session.query(CalendarConnection).one()

    import httpx
    with patch("app.calendar_tokens.httpx.post",
               side_effect=httpx.ConnectError("network down")):
        response = client.delete(f"/api/calendars/{connection.id}")

    assert response.status_code == 204
    assert db_session.query(CalendarConnection).count() == 0


# --- Ownership ----------------------------------------------------------

def test_another_users_connection_is_not_visible(callback, client, db_session):
    callback()
    stolen = db_session.query(CalendarConnection).one()
    # Reassign it to somebody else.
    other = User(email="someone-else@example.com")
    db_session.add(other)
    db_session.commit()
    stolen.user_id = other.id
    db_session.commit()

    assert client.get("/api/calendars").json()["connections"] == []
    assert client.patch(f"/api/calendars/{stolen.id}",
                        json={"default_kind": "work"}).status_code == 404
    assert client.delete(f"/api/calendars/{stolen.id}").status_code == 404


def test_calendar_endpoints_require_a_session(db_session):
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        anonymous = TestClient(app)
        assert anonymous.get("/api/calendars").status_code == 401
        assert anonymous.get("/api/calendars/google/connect",
                             follow_redirects=False).status_code == 401
    finally:
        app.dependency_overrides.clear()
