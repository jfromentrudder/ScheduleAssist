from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql://scheduleassist:scheduleassist@localhost:5432/scheduleassist"
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
