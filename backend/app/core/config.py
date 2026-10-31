"""Application settings.

All configuration is read from environment variables (and, for local development,
from ``backend/.env``). Business logic never reads ``os.environ`` directly; it
receives a ``Settings`` instance via ``get_settings()``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]

APP_VERSION = "1.0.0"
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "SakshamPay"
    APP_ENV: Literal["development", "test", "production"] = "development"
    APP_VERSION: str = APP_VERSION
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # Database (not required until models are introduced)
    DATABASE_URL: str | None = None

    # Authentication (used from P-3)
    JWT_SECRET_KEY: SecretStr | None = None
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # Logging
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"

    @field_validator("DATABASE_URL", "JWT_SECRET_KEY", mode="before")
    @classmethod
    def _empty_string_is_unset(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def _use_psycopg3_driver(cls, value: str | None) -> str | None:
        """Hosting providers hand out postgres:// or postgresql:// URLs; SQLAlchemy
        needs the explicit psycopg 3 driver name."""
        if value is None:
            return None
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _upper_log_level(cls, value):
        return value.upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _production_safety(self) -> "Settings":
        if self.APP_ENV == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be false when APP_ENV=production")
            secret = self.JWT_SECRET_KEY.get_secret_value() if self.JWT_SECRET_KEY else ""
            if len(secret) < MIN_JWT_SECRET_LENGTH:
                raise ValueError(
                    f"JWT_SECRET_KEY must be set and at least {MIN_JWT_SECRET_LENGTH} characters "
                    "when APP_ENV=production"
                )
            if any(origin == "*" for origin in self.cors_origins):
                raise ValueError("FRONTEND_ORIGIN must not be '*' in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.FRONTEND_ORIGIN.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs are available outside production only (P-1 decision)."""
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()
