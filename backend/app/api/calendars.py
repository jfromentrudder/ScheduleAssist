"""Connecting a calendar account.

Deliberately separate from sign-in. Reading someone's calendar is a bigger ask
than identifying them, so it is a second consent with its own redirect URI —
a user who signs in with Google is still asked explicitly, and a user who
signed in some other way can still connect a Google calendar.

Token refresh and revocation live in `app/calendar_tokens.py`; this module
covers the handshake that creates the connection and the endpoints that manage
it afterwards.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user, oauth
from app.integrations.tokens import (
    GOOGLE_CALENDAR_SCOPE,
    CalendarReauthRequired,
    apply_token_response,
    disconnect,
    get_access_token,
)
from app.config import settings
from app.database import get_db
from app.models import Calendar, CalendarConnection, CalendarKind, User
from app.api.periods import clear_orphaned_periods
from app.integrations.sync import clear_calendar, sync_calendar, sync_connection, sync_quietly

router = APIRouter(prefix="/api/calendars", tags=["calendars"])

# Where the chosen calendar kind waits while the user is away at Google's
# consent screen. Held in the signed OAuth session cookie, not a query
# parameter, so it cannot be tampered with on the way back.
KIND_SESSION_KEY = "calendar_connect_kind"

# Requested alongside the calendar scope so the callback can identify *which*
# Google account was connected. Without an ID token we would have no stable
# provider_account_id and could not tell two connected calendars apart.
CALENDAR_SCOPES = f"openid email {GOOGLE_CALENDAR_SCOPE}"

oauth.register(
    name="google_calendar",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": CALENDAR_SCOPES},
)


def _calendar_json(calendar: Calendar) -> dict:
    return {
        "id": calendar.id,
        "name": calendar.name,
        "description": calendar.description,
        "color": calendar.color,
        "is_primary": calendar.is_primary,
        "selected": calendar.selected,
        "kind": calendar.kind.value,
        "last_synced_at": calendar.last_synced_at,
        "last_sync_error": calendar.last_sync_error,
    }


def _connection_json(connection: CalendarConnection) -> dict:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "account_email": connection.account_email,
        "default_kind": connection.default_kind.value,
        "created_at": connection.created_at,
        "last_synced_at": connection.last_synced_at,
        "last_sync_error": connection.last_sync_error,
        # False once the user revokes access at the provider; the UI uses this
        # to prompt a reconnect rather than silently showing stale events.
        "healthy": connection.refresh_token is not None,
        # Primary first, then alphabetical: the order these appear in Google.
        "calendars": [
            _calendar_json(c) for c in sorted(
                connection.calendars,
                key=lambda c: (not c.is_primary, c.name.lower()))
        ],
    }


def _redirect_to_settings(error: str | None = None) -> RedirectResponse:
    """Send the browser back to the settings page, with an error to act on.

    Failures here are recoverable — the user declined, or unticked the calendar
    permission — so the UI offers a retry rather than a dead end. The target is
    the page the calendar list lives on, so the outcome lands where the user
    started the flow.
    """
    suffix = f"?calendar_error={error}" if error else "?calendar_connected=1"
    return RedirectResponse(f"{settings.frontend_url}/settings{suffix}")


@router.get("")
def list_connections(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    connections = db.scalars(
        select(CalendarConnection)
        .where(CalendarConnection.user_id == user.id)
        .order_by(CalendarConnection.created_at)
    ).all()
    return {"connections": [_connection_json(c) for c in connections]}


@router.get("/google/connect")
async def connect_google(
    request: Request,
    kind: CalendarKind = CalendarKind.PERSONAL,
    user: User = Depends(get_current_user),
):
    """Start the calendar consent flow for the signed-in user."""
    request.session[KIND_SESSION_KEY] = kind.value
    return await oauth.google_calendar.authorize_redirect(
        request,
        settings.google_calendar_redirect_uri,
        # Google only issues a refresh token when both are set, and without one
        # the connection dies the first time the access token expires.
        access_type="offline",
        prompt="consent",
        # Incremental auth: keep any scope the user has already granted.
        include_granted_scopes="true",
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store the granted calendar access as a CalendarConnection."""
    kind = CalendarKind(
        request.session.pop(KIND_SESSION_KEY, CalendarKind.PERSONAL.value))

    try:
        token = await oauth.google_calendar.authorize_access_token(request)
    except Exception:
        # Denied consent, or a stale/replayed state parameter.
        return _redirect_to_settings("denied")

    # The user can untick individual permissions on the consent screen, so a
    # successful handshake does not prove we got what we asked for.
    if GOOGLE_CALENDAR_SCOPE not in token.get("scope", "").split():
        return _redirect_to_settings("scope")

    info = token.get("userinfo") or {}
    subject = info.get("sub")
    if not subject:
        return _redirect_to_settings("identity")

    connection = db.scalar(
        select(CalendarConnection).where(
            CalendarConnection.user_id == user.id,
            CalendarConnection.provider == "google",
            CalendarConnection.provider_account_id == subject,
        )
    )
    if connection is None:
        connection = CalendarConnection(
            user_id=user.id, provider="google", provider_account_id=subject)
        db.add(connection)

    # Reconnecting an existing account refreshes its tokens and clears the
    # error that prompted the reconnect in the first place.
    connection.account_email = info.get("email")
    # Seeds the calendars discovered by the import below; each can be changed
    # individually afterwards.
    connection.default_kind = kind
    connection.last_sync_error = None
    apply_token_response(connection, token)
    db.commit()

    # Import straight away: a calendar that shows nothing until the user finds
    # a sync button does not look connected. Failures are recorded on the
    # connection rather than raised, since the connection itself succeeded.
    sync_quietly(db, connection)

    return _redirect_to_settings()


class ConnectionUpdate(BaseModel):
    """The account-level default applied to calendars discovered later."""

    default_kind: CalendarKind


class CalendarUpdate(BaseModel):
    """Both optional so the UI can tick a box without also setting a kind."""

    selected: bool | None = None
    kind: CalendarKind | None = None


def _owned(
    connection_id: int, user: User, db: Session
) -> CalendarConnection:
    """Fetch a connection, 404ing on anything the user does not own.

    Scoped by user_id rather than checked afterwards, so a wrong id is
    indistinguishable from someone else's id.
    """
    connection = db.scalar(
        select(CalendarConnection).where(
            CalendarConnection.id == connection_id,
            CalendarConnection.user_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.patch("/{connection_id}")
def update_connection(
    connection_id: int,
    update: ConnectionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the default kind for calendars found on this account later."""
    connection = _owned(connection_id, user, db)
    connection.default_kind = update.default_kind
    db.commit()
    return _connection_json(connection)


def _owned_calendar(
    connection_id: int, calendar_id: int, user: User, db: Session
) -> Calendar:
    connection = _owned(connection_id, user, db)
    calendar = db.scalar(
        select(Calendar).where(
            Calendar.id == calendar_id,
            Calendar.calendar_connection_id == connection.id,
        )
    )
    if calendar is None:
        raise HTTPException(status_code=404, detail="Calendar not found")
    return calendar


@router.patch("/{connection_id}/calendars/{calendar_id}")
def update_calendar(
    connection_id: int,
    calendar_id: int,
    update: CalendarUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Tick or untick a calendar, or change how its events are read.

    Ticking imports immediately so the schedule fills in straight away;
    unticking removes what that calendar contributed.
    """
    calendar = _owned_calendar(connection_id, calendar_id, user, db)
    was_selected = calendar.selected

    if update.kind is not None:
        calendar.kind = update.kind
    if update.selected is not None:
        calendar.selected = update.selected
    db.commit()

    removed = imported = 0
    if update.selected is False and was_selected:
        removed = clear_calendar(db, calendar)
    elif calendar.selected:
        # Newly ticked, or the kind changed and everything needs reclassifying.
        if update.kind is not None and update.selected is None:
            calendar.sync_token = None
            db.commit()
        try:
            result = sync_calendar(
                db, calendar,
                get_access_token(db, calendar.connection),
                now=datetime.now(timezone.utc),
            )
            imported = result.created + result.updated
        except CalendarReauthRequired:
            raise HTTPException(
                status_code=409, detail="Calendar needs reconnecting") from None
        except Exception as failure:  # noqa: BLE001 - reported on the calendar
            calendar.last_sync_error = f"Could not import events: {failure}"
            db.commit()

    return {
        "calendar": _calendar_json(calendar),
        "events_imported": imported,
        "events_removed": removed,
    }


@router.post("/{connection_id}/sync")
def resync_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pull in whatever has changed since the last sync."""
    connection = _owned(connection_id, user, db)
    try:
        result = sync_connection(db, connection)
    except CalendarReauthRequired:
        # Nothing we can retry: the user has to grant access again.
        connection.last_sync_error = (
            "Access expired. Please reconnect this calendar.")
        db.commit()
        raise HTTPException(
            status_code=409, detail="Calendar needs reconnecting") from None

    return {
        "created": result.created,
        "updated": result.updated,
        "deleted": result.deleted,
        "full_resync": result.full_resync,
        "connection": _connection_json(connection),
    }


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke the grant at Google and remove the connection.

    Imported events cascade away with it — a decision already baked into the
    schema. The periods generated for those events do not cascade, because they
    belong to the user rather than to the calendar, so they are cleared here:
    time held for a deadline that has just been removed is time held for
    nothing.
    """
    disconnect(db, _owned(connection_id, user, db))
    clear_orphaned_periods(db, user.id)
