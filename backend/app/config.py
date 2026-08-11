from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql://scheduleassist:scheduleassist@localhost:5432/scheduleassist"

    # The two origins this app lives at. Every absolute URL it builds is
    # derived from one of them, so moving to a real domain is a change in one
    # place rather than a hunt for hardcoded hosts.
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    # Extra browser origins allowed to call the API. Usually empty: the
    # frontend's own origin is always allowed, see `allowed_origins`.
    cors_origins: list[str] = []

    # Google OAuth. One client covers both sign-in and calendar access, but
    # they are separate consents with separate callbacks, so signing in never
    # asks for calendar permission.
    google_client_id: str = ""
    google_client_secret: str = ""

    # Signs the temporary cookie that holds OAuth state/nonce during the handshake
    secret_key: str = "dev-only-secret-change-in-prod"

    # Fernet key encrypting stored calendar OAuth tokens. No default:
    # a shared fallback key would be no better than storing them in plaintext.
    # Generate with:
    #   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    calendar_token_key: str = ""

    @field_validator("backend_url", "frontend_url")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        # Paths are appended directly below, and "host//api/..." would not
        # match the redirect URI registered with Google.
        return value.rstrip("/")

    @property
    def google_redirect_uri(self) -> str:
        """Sign-in callback. Must be registered on the OAuth client exactly."""
        return f"{self.backend_url}/api/auth/google/callback"

    @property
    def google_calendar_redirect_uri(self) -> str:
        """Calendar-consent callback. Also registered on the OAuth client."""
        return f"{self.backend_url}/api/calendars/google/callback"

    @property
    def allowed_origins(self) -> list[str]:
        """Origins permitted by CORS: the frontend, plus any extras."""
        return [self.frontend_url, *self.cors_origins]


settings = Settings()
