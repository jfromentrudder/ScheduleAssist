import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuthIdentity, User, UserSession

SESSION_COOKIE = "session_token"
SESSION_TTL = timedelta(days=7)
_COOKIE_FLAGS = {
    "path": "/",
    "httponly": True,
    "samesite": "lax",
    "secure": settings.frontend_url.startswith("https"),
}

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    # Sign-in only. Calendar scopes are requested separately when the user
    # connects a calendar, regardless of how they signed in.
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _as_utc(value: datetime) -> datetime:
    """Postgres returns aware datetimes; SQLite (used in tests) does not."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def create_session(db: Session, user: User) -> str:
    """Create a DB session row and return the raw token for the cookie."""
    raw = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(timezone.utc) + SESSION_TTL,
        )
    )
    db.commit()
    return raw


def set_session_cookie(response: Response, raw: str) -> None:
    response.set_cookie(SESSION_COOKIE, raw, max_age=int(
        SESSION_TTL.total_seconds()), **_COOKIE_FLAGS)


def clear_session_cookie(response: Response) -> None:
    # Flags must match set_session_cookie or the browser keeps the old cookie.
    response.delete_cookie(SESSION_COOKIE, **_COOKIE_FLAGS)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the signed-in user, or 401. Depend on this to protect a route."""
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        session = db.scalar(
            select(UserSession).where(
                UserSession.token_hash == _hash_token(raw))
        )
        if session and _as_utc(session.expires_at) > datetime.now(timezone.utc):
            return session.user
    raise HTTPException(status_code=401, detail="Not authenticated")


@router.get("/google/login")
async def google_login(request: Request):
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        # User denied consent, or state/nonce validation failed
        return RedirectResponse(f"{settings.frontend_url}/signin?auth_error=1")

    info = token["userinfo"]  # verified ID-token claims
    if not info.get("email_verified"):
        raise HTTPException(
            status_code=400, detail="Google account email is not verified")

    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "google",
            AuthIdentity.provider_subject == info["sub"],
        )
    )
    if identity:
        user = identity.user
    else:
        # Google verified this email, so it is safe to link the identity to an
        # existing account with the same address (e.g. one created later via
        # email/password).
        user = db.scalar(select(User).where(User.email == info["email"]))
        if user is None:
            user = User(email=info["email"], display_name=info.get("name"))
            db.add(user)
        user.identities.append(
            AuthIdentity(provider="google", provider_subject=info["sub"])
        )
        db.commit()

    response = RedirectResponse(settings.frontend_url)
    set_session_cookie(response, create_session(db, user))
    return response


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        # Included here so the UI can apply the saved theme on first paint
        # rather than after a second request.
        "theme": user.theme.value,
        "appearance": user.appearance.value,
        # The week grid positions every block in this zone, and needs it before
        # it can decide which week "this week" even is.
        "timezone": user.timezone,
    }


@router.post("/logout", status_code=204)
def logout(request: Request, db: Session = Depends(get_db)):
    """Invalidate the current session. Safe to call when already signed out."""
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        db.execute(delete(UserSession).where(
            UserSession.token_hash == _hash_token(raw)))
        db.commit()

    response = Response(status_code=204)
    clear_session_cookie(response)
    return response
