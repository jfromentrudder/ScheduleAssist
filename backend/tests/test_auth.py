"""Tests for sign-in, sessions, and the guard every protected route depends on.

Auth was the one area named in #16 with no tests of its own: the rest of the
suite used the authenticated `client` fixture without ever checking what makes
it authenticated, so the 401 path and the session lifecycle were untested.

Google's consent screen cannot be driven from a test — Google blocks it — so
these start where the callback returns, with a canned token response. That is
also where all the logic lives; everything before it belongs to Authlib.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from authlib.integrations.starlette_client import OAuthError

from app.auth import SESSION_COOKIE, SESSION_TTL, create_session
from app.models import AuthIdentity, User, UserSession


def token_response(**claims) -> dict:
    """What Authlib hands back after it has verified the ID token."""
    userinfo = {
        "sub": "google-sub-1",
        "email": "new@example.com",
        "email_verified": True,
        "name": "New Person",
    }
    userinfo.update(claims)
    return {"userinfo": userinfo}


@pytest.fixture
def callback(client):
    """Drive the sign-in callback with a canned token response."""
    def run(token=None, raises=None):
        with patch("app.auth.oauth.google.authorize_access_token") as authorize:
            if raises is not None:
                authorize.side_effect = raises
            else:
                authorize.return_value = token or token_response()
            return client.get(
                "/api/auth/google/callback", follow_redirects=False)
    return run


# --- The session guard ---------------------------------------------------

def test_a_protected_route_rejects_an_anonymous_request(client):
    client.cookies.clear()

    assert client.get("/api/auth/me").status_code == 401


def test_a_protected_route_rejects_an_unknown_token(client):
    client.cookies.set(SESSION_COOKIE, "not-a-real-token")

    assert client.get("/api/auth/me").status_code == 401


def test_an_expired_session_is_rejected(client, db_session, user):
    """The row still exists; only its expiry has passed."""
    raw = create_session(db_session, user)
    # Looked up by its own hash: the authenticated `client` fixture already
    # holds a session of its own, so this is not the only row in the table.
    session = db_session.query(UserSession).filter(
        UserSession.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    ).one()
    session.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    client.cookies.set(SESSION_COOKIE, raw)

    assert client.get("/api/auth/me").status_code == 401


def test_a_live_session_identifies_its_user(client, user):
    body = client.get("/api/auth/me").json()

    assert body["id"] == user.id
    assert body["email"] == "test@example.com"


def test_me_carries_what_the_first_paint_needs(client):
    """Theme and timezone ride along so the UI does not need a second request."""
    body = client.get("/api/auth/me").json()

    assert body["theme"] == "ember"
    assert body["appearance"] == "system"
    assert body["timezone"] == "UTC"


def test_the_raw_token_is_never_stored(db_session, user):
    """Only a hash is kept, so a leaked database cannot be used to sign in."""
    raw = create_session(db_session, user)
    session = db_session.query(UserSession).one()

    assert session.token_hash != raw
    assert session.token_hash == hashlib.sha256(raw.encode()).hexdigest()


def test_sessions_expire_a_week_out(db_session, user):
    create_session(db_session, user)
    session = db_session.query(UserSession).one()
    expires = session.expires_at
    if expires.tzinfo is None:  # SQLite drops the zone; Postgres keeps it.
        expires = expires.replace(tzinfo=timezone.utc)

    remaining = expires - datetime.now(timezone.utc)
    assert timedelta(days=6) < remaining <= SESSION_TTL


def test_one_user_can_hold_several_sessions(client, db_session, user):
    """Signing in on a second device must not sign the first one out."""
    first = create_session(db_session, user)
    second = create_session(db_session, user)

    for raw in (first, second):
        client.cookies.set(SESSION_COOKIE, raw)
        assert client.get("/api/auth/me").status_code == 200


# --- Signing in ----------------------------------------------------------

def test_a_first_sign_in_creates_the_account(callback, db_session):
    response = callback()

    assert response.status_code == 307
    assert SESSION_COOKIE in response.cookies

    created = db_session.query(User).filter(
        User.email == "new@example.com").one()
    assert created.display_name == "New Person"
    identity = db_session.query(AuthIdentity).filter(
        AuthIdentity.user_id == created.id).one()
    assert identity.provider == "google"
    assert identity.provider_subject == "google-sub-1"


def test_signing_in_again_reuses_the_same_account(callback, db_session):
    callback()
    callback()

    assert db_session.query(User).filter(
        User.email == "new@example.com").count() == 1
    assert db_session.query(AuthIdentity).count() == 1
    # A second sign-in is a second session, not a second account.
    assert db_session.query(UserSession).count() >= 2


def test_a_verified_google_email_links_to_an_existing_account(
        callback, db_session, user):
    """Google has verified the address, so it is safe to attach the identity to
    an account that already owns it — the path an email/password user takes when
    they later sign in with Google."""
    response = callback(token_response(email=user.email, sub="google-sub-2"))

    assert response.status_code == 307
    assert db_session.query(User).filter(User.email == user.email).count() == 1
    identity = db_session.query(AuthIdentity).filter(
        AuthIdentity.provider_subject == "google-sub-2").one()
    assert identity.user_id == user.id


def test_an_unverified_email_is_refused(callback, db_session):
    """Without this, anyone able to set an unverified address on a Google
    account could claim someone else's."""
    response = callback(token_response(email_verified=False))

    assert response.status_code == 400
    assert db_session.query(User).filter(
        User.email == "new@example.com").count() == 0


def test_declining_consent_returns_to_sign_in_with_a_reason(callback):
    response = callback(raises=OAuthError("access_denied"))

    assert response.status_code == 307
    assert "auth_error=1" in response.headers["location"]


def test_a_failed_sign_in_creates_nothing(callback, db_session):
    before = db_session.query(User).count()

    callback(raises=OAuthError("access_denied"))

    assert db_session.query(User).count() == before
    assert db_session.query(AuthIdentity).count() == 0


# --- Signing out ---------------------------------------------------------

def test_logging_out_invalidates_the_session(client, db_session, user):
    raw = create_session(db_session, user)
    client.cookies.set(SESSION_COOKIE, raw)

    assert client.post("/api/auth/logout").status_code == 204

    client.cookies.set(SESSION_COOKIE, raw)
    assert client.get("/api/auth/me").status_code == 401


def test_logging_out_removes_only_that_session(client, db_session, user):
    """Signing out on one device leaves the others alone."""
    keep = create_session(db_session, user)
    drop = create_session(db_session, user)

    client.cookies.set(SESSION_COOKIE, drop)
    client.post("/api/auth/logout")

    client.cookies.set(SESSION_COOKIE, keep)
    assert client.get("/api/auth/me").status_code == 200


def test_logging_out_twice_is_not_an_error(client):
    """The button is reachable from a stale tab, so it has to be idempotent."""
    assert client.post("/api/auth/logout").status_code == 204
    assert client.post("/api/auth/logout").status_code == 204


def test_logging_out_clears_the_cookie(client):
    response = client.post("/api/auth/logout")

    # Starlette expresses deletion as an immediate expiry.
    assert 'session_token=""' in response.headers.get("set-cookie", "")


# --- Cookie hardening ----------------------------------------------------

def test_the_session_cookie_is_not_readable_by_scripts(callback):
    header = callback().headers["set-cookie"]

    assert "HttpOnly" in header
    # Lax rather than Strict: the cookie is set during a redirect back from
    # Google, and Strict would drop it on that navigation.
    assert "SameSite=lax" in header
