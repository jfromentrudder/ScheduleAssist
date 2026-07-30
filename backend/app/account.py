from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.auth import clear_session_cookie, get_current_user
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("")
def get_account(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "created_at": user.created_at,
        "providers": sorted({identity.provider for identity in user.identities}),
    }


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
