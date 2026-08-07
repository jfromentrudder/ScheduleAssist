"""Account management for the signed-in user."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import clear_session_cookie, get_current_user
from app.database import get_db
from app.models import Appearance, Theme, User
from app.scheduler import MAX_HORIZON_DAYS, MIN_HORIZON_DAYS, horizon_warning

router = APIRouter(prefix="/api/account", tags=["account"])


class AccountUpdate(BaseModel):
    """Every field optional so the UI can save one control at a time.

    Pydantic rejects anything outside the enums or the horizon range with a 422
    before it reaches the database, where the same bounds are a CHECK
    constraint.
    """

    theme: Theme | None = None
    appearance: Appearance | None = None
    schedule_horizon_days: int | None = Field(
        default=None, ge=MIN_HORIZON_DAYS, le=MAX_HORIZON_DAYS)


def _account_json(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at,
        "providers": sorted({identity.provider for identity in user.identities}),
        "theme": user.theme.value,
        "appearance": user.appearance.value,
        "schedule_horizon_days": user.schedule_horizon_days,
        # Non-null at either extreme of the range, for the settings UI to show.
        "schedule_horizon_warning": horizon_warning(user.schedule_horizon_days),
    }


@router.get("")
def get_account(user: User = Depends(get_current_user)):
    return _account_json(user)


@router.patch("")
def update_account(
    update: AccountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Save the user's appearance and scheduling preferences."""
    if update.theme is not None:
        user.theme = update.theme
    if update.appearance is not None:
        user.appearance = update.appearance
    if update.schedule_horizon_days is not None:
        # Shrinking the horizon does not itself reschedule anything; the next
        # generate pass simply has fewer locked periods to work around.
        user.schedule_horizon_days = update.schedule_horizon_days
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
