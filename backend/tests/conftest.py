"""Test fixtures backing the API tests with an in-memory SQLite database.

SQLite rather than Postgres so the suite runs with no Docker and no network,
which matters for CI. The models are portable by design — enums are VARCHAR +
CHECK, and encrypted columns are LargeBinary — but SQLite drops timezone
information on the way out, which is exactly why the engine normalizes naive
datetimes to UTC on entry.
"""

import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# The app reads settings at import time and the crypto module needs a valid
# Fernet key, so both must exist before anything under app.* is imported.
os.environ.setdefault("CALENDAR_TOKEN_KEY",
                      "zH8Nn0kqOQZ3vJ6yQm1sVYd2lXrPfKcTgWbEuAiNjRk=")

from app.auth import SESSION_COOKIE, create_session  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly on any unpatched outbound request.

    Without this a test can quietly call Google for real: slow, flaky, and
    dependent on whoever is running it. Tests that exercise provider calls
    patch the specific function they need on top of this.
    """
    def blocked(*args, **kwargs):
        raise RuntimeError(
            "test attempted a real network call — patch the client instead")

    monkeypatch.setattr(httpx, "get", blocked)
    monkeypatch.setattr(httpx, "post", blocked)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # One shared in-memory DB across connections.
    )

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, _record):
        # SQLite ignores foreign keys unless asked, and the cascades this app
        # relies on would silently not fire.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def user(db_session):
    """A signed-in user on the defaults: Mon-Fri, 9-5 UTC, 5-day horizon."""
    record = User(email="test@example.com", display_name="Test")
    db_session.add(record)
    db_session.commit()
    return record


@pytest.fixture
def client(db_session, user):
    """An authenticated TestClient sharing the fixture session."""
    app.dependency_overrides[get_db] = lambda: db_session
    test_client = TestClient(app)
    test_client.cookies.set(SESSION_COOKIE, create_session(db_session, user))
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()
