"""Removing a generated period by hand.

Periods are derived data — generating again replaces them — but a user still
needs to delete one directly. The block might sit over something the calendar
does not know about, or be a meal break they do not want held that day.

Cleanup of periods orphaned by a *deleted event* is a different job with
different callers, and lives in `app/planning.py` beside the code that writes
them.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.core.scheduler import PeriodPlan, freeze_boundary, is_locked
from app.database import get_db
from app.models import Period, User

router = APIRouter(prefix="/api/periods", tags=["periods"])


@router.delete("/{period_id}", status_code=204)
def delete_period(
    period_id: int,
    confirm: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove one generated period.

    A period inside the commitment horizon is *settled*: the user has been told
    that part of their schedule will stay put, and may have planned around it.
    Deleting one is allowed, but not silently — the first call reports the
    conflict and the client repeats it with `confirm=true` once the user has
    seen the warning. This is the same "the engine reports, the user decides"
    rule the generator follows.

    Periods beyond the horizon need no confirmation, because the next
    generation was free to move them anyway.
    """
    period = db.scalar(
        select(Period).where(Period.id == period_id, Period.user_id == user.id))
    if period is None:
        raise HTTPException(status_code=404, detail="Period not found")

    boundary = freeze_boundary(
        datetime.now(timezone.utc),
        user.schedule_horizon_days,
        ZoneInfo(user.timezone),
    )
    settled = is_locked(
        PeriodPlan(period.starts_at, period.ends_at, ()), boundary)

    if settled and not confirm:
        raise HTTPException(
            status_code=409,
            detail=(
                "That period is settled — it sits inside your planning "
                "horizon, where the schedule is meant to stay put. Deleting "
                "it frees the time, but the work it was holding will be "
                "scheduled again the next time you generate."
            ),
        )

    db.delete(period)
    db.commit()
