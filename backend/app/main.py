from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.account import router as account_router
from app.auth import router as auth_router
from app.calendars import router as calendars_router
from app.config import settings
from app.database import get_db
from app.schedule import router as schedule_router

# Schema is managed by Alembic: run `alembic upgrade head` to apply migrations.
app = FastAPI(title="ScheduleAssist API")

# Only used by Authlib to hold OAuth state/nonce across the redirect handshake;
# app sessions live in the sessions table, not in this cookie.
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(calendars_router)
app.include_router(schedule_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}
