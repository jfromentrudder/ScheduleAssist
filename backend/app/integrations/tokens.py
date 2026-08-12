"""Access-token lifecycle for calendar connections.

Connections are created by the consent flow and read by the event
importer; this module owns everything in between: handing out a
usable access token, refreshing it before it expires, and revoking it on
disconnect.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import CalendarConnection

# Read-only calendar access. Requested separately from the sign-in scopes so a
# user is never asked for calendar permission just to log in.
GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"

# Refresh this far ahead of expiry so a token cannot lapse mid-request.
REFRESH_SKEW = timedelta(minutes=5)


class CalendarReauthRequired(Exception):
    """The connection can no longer be refreshed; the user must reconnect.

    Raised when there is no refresh token, or the provider rejected it because
    the user revoked access or changed their password.
    """

    def __init__(self, connection_id: int, reason: str):
        super().__init__(
            f"connection {connection_id} needs reauthorization: {reason}")
        self.connection_id = connection_id
        self.reason = reason


@dataclass(frozen=True)
class Provider:
    token_url: str
    revoke_url: str
    client_id: str
    client_secret: str


def _provider(name: str) -> Provider:
    if name == "google":
        # Same OAuth client as sign-in; only the scopes differ.
        return Provider(
            token_url="https://oauth2.googleapis.com/token",
            revoke_url="https://oauth2.googleapis.com/revoke",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )
    raise ValueError(f"unsupported calendar provider: {name}")


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def needs_refresh(connection: CalendarConnection, *, now: datetime | None = None) -> bool:
    """True when the access token is expired or about to be."""
    if connection.access_token_expires_at is None:
        # No expiry recorded; treat as long-lived until told otherwise.
        return False
    now = now or datetime.now(timezone.utc)
    return _as_utc(connection.access_token_expires_at) - REFRESH_SKEW <= now


def get_access_token(db: Session, connection: CalendarConnection) -> str:
    """Return a usable access token, refreshing first if it is close to expiry.

    Callers making provider API calls should always go through this rather than
    reading `connection.access_token` directly.
    """
    if needs_refresh(connection):
        refresh_access_token(db, connection)
    return connection.access_token


def refresh_access_token(db: Session, connection: CalendarConnection) -> str:
    """Exchange the refresh token for a new access token and persist it."""
    if not connection.refresh_token:
        raise CalendarReauthRequired(connection.id, "no refresh token stored")

    provider = _provider(connection.provider)
    response = httpx.post(
        provider.token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": connection.refresh_token,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        },
        timeout=10,
    )

    if response.status_code == 400:
        # invalid_grant: the user revoked access, or the token was expired by
        # the provider. No amount of retrying fixes this.
        raise CalendarReauthRequired(
            connection.id, response.json().get("error", "invalid_grant"))
    response.raise_for_status()

    payload = response.json()
    apply_token_response(connection, payload)
    db.commit()
    return connection.access_token


def apply_token_response(connection: CalendarConnection, payload: dict) -> None:
    """Copy an OAuth token response onto the connection (without committing).

    Shared by the initial consent flow and refresh. A refresh response
    normally omits `refresh_token`, so the stored one is kept.
    """
    connection.access_token = payload["access_token"]
    if payload.get("refresh_token"):
        connection.refresh_token = payload["refresh_token"]
    if payload.get("scope"):
        connection.scopes = payload["scope"]

    expires_in = payload.get("expires_in")
    connection.access_token_expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )


def disconnect(db: Session, connection: CalendarConnection) -> None:
    """Revoke the grant with the provider, then delete the connection.

    Revocation is best-effort: if the provider call fails we still remove the
    row, because leaving a connection the user asked to delete is worse than a
    stale grant they can clear from their provider's account settings.
    """
    provider = _provider(connection.provider)
    token = connection.refresh_token or connection.access_token
    if token:
        try:
            httpx.post(provider.revoke_url, data={"token": token}, timeout=10)
        except httpx.HTTPError:
            pass

    db.delete(connection)
    db.commit()
