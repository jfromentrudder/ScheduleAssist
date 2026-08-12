"""Account management for the signed-in user."""

from datetime import time
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import clear_session_cookie, get_current_user
from app.database import get_db
from app.models import Appearance, Theme, User
from app.scheduler import (
    MAX_HORIZON_DAYS, MAX_LUNCH_MINUTES, MAX_PERIOD_MINUTES, MIN_HORIZON_DAYS,
    MIN_LUNCH_MINUTES, MIN_PERIOD_MINUTES, WEEKDAYS, horizon_warning,
)

# Preferences that decide *where* periods may go. Changing any of them leaves
# the existing schedule describing rules that no longer apply — periods sitting
# outside the new working hours, or in the old timezone — so it has to be
# rebuilt rather than added to.
#
# The horizon is deliberately absent: it changes which periods are protected
# from here on, but every period already placed is still valid under it.
SCHEDULING_FIELDS = frozenset({
    "workdays", "day_start", "day_end", "period_minutes", "lunch_minutes",
    "timezone",
})

router = APIRouter(prefix="/api/account", tags=["account"])


class AccountUpdate(BaseModel):
    """Every field optional so the UI can save one control at a time.

    Pydantic rejects anything outside the enums or the allowed ranges with a
    422 before it reaches the database, where the same bounds are CHECK
    constraints.
    """

    theme: Theme | None = None
    appearance: Appearance | None = None
    schedule_horizon_days: int | None = Field(
        default=None, ge=MIN_HORIZON_DAYS, le=MAX_HORIZON_DAYS)

    # --- Scheduling preferences ---
    workdays: list[int] | None = None
    day_start: time | None = None
    day_end: time | None = None
    period_minutes: int | None = Field(
        default=None, ge=MIN_PERIOD_MINUTES, le=MAX_PERIOD_MINUTES)
    lunch_minutes: int | None = Field(
        default=None, ge=MIN_LUNCH_MINUTES, le=MAX_LUNCH_MINUTES)
    timezone: str | None = None

    @field_validator("workdays")
    @classmethod
    def _valid_weekdays(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(day not in WEEKDAYS for day in value):
            raise ValueError("workdays must be weekday numbers, Monday = 0")
        # Sorted and de-duplicated so the stored value has one canonical form.
        return sorted(set(value))

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in available_timezones():
            raise ValueError(f"unknown timezone: {value}")
        return value


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
        "workdays": user.workdays,
        "day_start": user.day_start,
        "day_end": user.day_end,
        "period_minutes": user.period_minutes,
        "lunch_minutes": user.lunch_minutes,
        "timezone": user.timezone,
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
    fields = update.model_dump(exclude_unset=True, exclude_none=True)

    # Checked against the merged result, not the payload, so sending only one
    # end of the working day is still validated against the other.
    day_start = fields.get("day_start", user.day_start)
    day_end = fields.get("day_end", user.day_end)
    if day_end <= day_start:
        raise HTTPException(
            status_code=422, detail="The day must end after it starts")

    for field, value in fields.items():
        setattr(user, field, value)
    db.commit()

    body = _account_json(user)
    # Tells the client the current schedule no longer reflects these settings.
    # Fixing it needs a *full* rebuild: the offending periods are usually the
    # settled ones, which an additive pass would preserve untouched.
    body["schedule_stale"] = bool(SCHEDULING_FIELDS & fields.keys())
    return body


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
