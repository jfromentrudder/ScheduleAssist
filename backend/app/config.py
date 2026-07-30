from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql://scheduleassist:scheduleassist@localhost:5432/scheduleassist"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Google OAuth (sign-in only; calendar access is a separate consent, issue #7)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"

    # Where to send the browser after a completed sign-in
    frontend_url: str = "http://localhost:5173"

    # Signs the temporary cookie that holds OAuth state/nonce during the handshake
    secret_key: str = "dev-only-secret-change-in-prod"

    # Fernet key encrypting stored calendar OAuth tokens. No default:
    # a shared fallback key would be no better than storing them in plaintext.
    # Generate with:
    #   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    calendar_token_key: str = ""


settings = Settings()
