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
    app_base_url: str = Field(
        default="http://localhost:8000", description="Public URL, used in links inside emails"
    )

    # Deadlines and reminders in working days (TZ 4.3)
    deadline_workdays: int = 10
    deadline_hour: int = 18  # local time on the deadline day

    # Mailbox of the system (TZ section 9, decision 1)
    mail_address: str = "rd@localhost"
    mail_display_name: str = "Ознакомление с РД"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_starttls: bool = False
    smtp_ssl: bool = False  # implicit TLS from the first byte (port 465, e.g. Mail.ru)
    smtp_auth: Literal["none", "oauth2", "password"] = "none"
    smtp_password: SecretStr = SecretStr("")
    smtp_timeout_seconds: float = 30
    mail_max_attempts: int = 5
    # Microsoft 365, used when smtp_auth / imap auth is "oauth2"
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: SecretStr = SecretStr("")

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
