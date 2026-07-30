"""Account management for the signed-in user."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import clear_session_cookie, get_current_user
from app.database import get_db
from app.models import Appearance, Theme, User

router = APIRouter(prefix="/api/account", tags=["account"])


class AppearanceUpdate(BaseModel):
    """Both fields optional so the UI can save one control at a time.

    Pydantic rejects anything outside the enums with a 422 before it reaches
    the database.
    """

    theme: Theme | None = None
    appearance: Appearance | None = None


def _account_json(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at,
        "providers": sorted({identity.provider for identity in user.identities}),
        "theme": user.theme.value,
        "appearance": user.appearance.value,
    }


@router.get("")
def get_account(user: User = Depends(get_current_user)):
    return _account_json(user)


@router.patch("")
def update_appearance(
    update: AppearanceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save the user's theme and light/dark choice."""
    if update.theme is not None:
        user.theme = update.theme
    if update.appearance is not None:
        user.appearance = update.appearance
    db.commit()
    return _account_json(user)


@router.delete("", status_code=204)
def delete_account(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Permanently delete the account. Identities and sessions cascade away."""
    db.delete(user)
    db.commit()

    response = Response(status_code=204)
    clear_session_cookie(response)
    return response
