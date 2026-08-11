"""Connecting a calendar account.

Deliberately separate from sign-in. Reading someone's calendar is a bigger ask
than identifying them, so it is a second consent with its own redirect URI —
a user who signs in with Google is still asked explicitly, and a user who
signed in some other way can still connect a Google calendar.

Token refresh and revocation live in `app/calendar_tokens.py`; this module
covers the handshake that creates the connection and the endpoints that manage
it afterwards.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, oauth
from app.calendar_tokens import (
    GOOGLE_CALENDAR_SCOPE,
    apply_token_response,
    disconnect,
)
from app.config import settings
from app.database import get_db
from app.models import CalendarConnection, CalendarKind, User

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


def _connection_json(connection: CalendarConnection) -> dict:
    return {
        "id": connection.id,
        "provider": connection.provider,
        "account_email": connection.account_email,
        "kind": connection.kind.value,
        "created_at": connection.created_at,
        "last_synced_at": connection.last_synced_at,
        "last_sync_error": connection.last_sync_error,
        # False once the user revokes access at the provider; the UI uses this
        # to prompt a reconnect rather than silently showing stale events.
        "healthy": connection.refresh_token is not None,
    }


def _redirect_to_account(error: str | None = None) -> RedirectResponse:
    """Send the browser back to the account page, with an error to act on.

    Failures here are recoverable — the user declined, or unticked the calendar
    permission — so the UI offers a retry rather than a dead end.
    """
    suffix = f"?calendar_error={error}" if error else "?calendar_connected=1"
    return RedirectResponse(f"{settings.frontend_url}/account{suffix}")


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
        return _redirect_to_account("denied")

    # The user can untick individual permissions on the consent screen, so a
    # successful handshake does not prove we got what we asked for.
    if GOOGLE_CALENDAR_SCOPE not in token.get("scope", "").split():
        return _redirect_to_account("scope")

    info = token.get("userinfo") or {}
    subject = info.get("sub")
    if not subject:
        return _redirect_to_account("identity")

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
    connection.kind = kind
    connection.last_sync_error = None
    apply_token_response(connection, token)
    db.commit()

    return _redirect_to_account()


class ConnectionUpdate(BaseModel):
    kind: CalendarKind


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
    """Change what sort of calendar this is, without reconnecting it."""
    connection = _owned(connection_id, user, db)
    connection.kind = update.kind
    db.commit()
    return _connection_json(connection)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke the grant at Google and remove the connection.

    Imported events cascade away with it — a decision already baked into the
    schema, which #8 can revisit.
    """
    disconnect(db, _owned(connection_id, user, db))
