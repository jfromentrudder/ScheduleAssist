"""Tests for derived configuration.

The redirect URIs must match what is registered on the Google OAuth client
byte for byte, and they are built by string concatenation, so the seams are
worth pinning down.
"""

import pytest

from app.config import Settings


def settings(**overrides) -> Settings:
    # _env_file=None so a developer's own .env cannot change the result.
    return Settings(_env_file=None, **overrides)


def test_both_callbacks_derive_from_one_setting():
    config = settings(backend_url="https://schedule.example.com")

    assert config.google_redirect_uri == (
        "https://schedule.example.com/api/auth/google/callback")
    assert config.google_calendar_redirect_uri == (
        "https://schedule.example.com/api/calendars/google/callback")


def test_sign_in_and_calendar_callbacks_stay_distinct():
    """Sharing one callback would collapse two deliberately separate consents."""
    config = settings()
    assert config.google_redirect_uri != config.google_calendar_redirect_uri


@pytest.mark.parametrize("url", [
    "http://localhost:8000/",
    "http://localhost:8000///",
])
def test_a_trailing_slash_does_not_produce_a_double_slash(url):
    """Google matches redirect URIs exactly; "host//api" would not match."""
    config = settings(backend_url=url)
    assert config.google_redirect_uri == (
        "http://localhost:8000/api/auth/google/callback")


def test_frontend_url_is_normalized_too():
    """It is concatenated with "/settings" on the way back from consent."""
    assert settings(frontend_url="http://localhost:5173/").frontend_url == (
        "http://localhost:5173")


def test_the_frontend_is_always_an_allowed_origin():
    config = settings(frontend_url="https://app.example.com")
    assert config.allowed_origins == ["https://app.example.com"]


def test_extra_cors_origins_are_added_not_substituted():
    """Setting CORS_ORIGINS must not lock the frontend out of its own API."""
    config = settings(
        frontend_url="https://app.example.com",
        cors_origins=["https://staging.example.com"],
    )
    assert config.allowed_origins == [
        "https://app.example.com", "https://staging.example.com"]


def test_defaults_are_local_development():
    config = settings()
    assert config.backend_url == "http://localhost:8000"
    assert config.frontend_url == "http://localhost:5173"
