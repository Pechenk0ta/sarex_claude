from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and `.env` in development)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    app_timezone: str = "Europe/Moscow"

    database_url: str = Field(
        default="postgresql+asyncpg://rd:rd@localhost:5432/rd",
        description="SQLAlchemy URL with the asyncpg driver",
    )
    secret_key: SecretStr = SecretStr("dev-insecure-change-me")
    session_max_age_hours: int = 12

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
