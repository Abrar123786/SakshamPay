"""Centralised application settings.

All configuration comes from environment variables, with ``backend/.env`` as a
local-development convenience. Business logic never reads ``os.environ``; it
receives a ``Settings`` instance (``get_settings()`` or ``app.state.settings``).

Development vs production
-------------------------
One ``Settings`` class serves every environment; ``APP_ENV`` selects the profile:

* **Environment-dependent defaults** apply only when a value is not set
  explicitly: ``DEBUG`` (on in development), ``LOG_FORMAT`` (console in
  development, json elsewhere) and ``LOG_LEVEL`` (DEBUG in development).
* **Production guard-rails** reject unsafe configurations at startup: debug
  mode, a missing or short JWT secret, a missing database URL, non-HTTPS or
  wildcard CORS origins, and SQL echo logging.

Secrets (``DATABASE_URL``, ``JWT_SECRET_KEY``, ``IDENTIFIER_HASH_KEY``) are ``SecretStr``: they never
appear in ``repr()``, logs or tracebacks. Use ``database_url_masked`` to log
where the database is.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

BACKEND_DIR = Path(__file__).resolve().parents[2]

APP_VERSION = "1.0.0"
MIN_JWT_SECRET_LENGTH = 32
MIN_IDENTIFIER_HASH_KEY_LENGTH = 32

Environment = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    APP_NAME: str = Field(default="SakshamPay", min_length=1, max_length=64)
    APP_ENV: Environment = "development"
    APP_VERSION: str = APP_VERSION
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Database --------------------------------------------------------------
    # Optional in development and test so the app starts without PostgreSQL.
    DATABASE_URL: SecretStr | None = None
    DB_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DB_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DB_POOL_TIMEOUT_SECONDS: int = Field(default=10, ge=1, le=120)
    DB_CONNECT_TIMEOUT_SECONDS: int = Field(default=5, ge=1, le=60)
    DB_STATEMENT_TIMEOUT_MS: int = Field(default=3000, ge=100, le=60_000)
    # Replace pooled connections older than this; managed hosts close long-idle connections.
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, ge=60, le=86_400)
    DB_ECHO: bool = False  # logs every SQL statement; never in production

    # --- Data protection ---------------------------------------------------------
    # HMAC key for fingerprints of beneficiary account references, UPI IDs and device IDs
    # (P-4 design). Changing it makes existing fingerprints unmatchable, so set it once.
    IDENTIFIER_HASH_KEY: SecretStr | None = None

    # --- Authentication (consumed from P-6) -------------------------------------
    JWT_SECRET_KEY: SecretStr | None = None
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, ge=1, le=1440)

    # --- HTTP --------------------------------------------------------------------
    FRONTEND_ORIGIN: str = "http://localhost:5173"  # comma-separated CORS allowlist
    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1024, le=10_485_760)

    # --- Logging -----------------------------------------------------------------
    LOG_LEVEL: LogLevel = "INFO"
    LOG_FORMAT: LogFormat = "json"

    # --- Field validation ----------------------------------------------------------
    @field_validator("DATABASE_URL", "JWT_SECRET_KEY", "IDENTIFIER_HASH_KEY", mode="before")
    @classmethod
    def _empty_string_is_unset(cls, value):
        """``.env.example`` ships with ``DATABASE_URL=``; treat blank as not configured."""
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalise_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        """Hosts hand out ``postgres://`` or ``postgresql://`` URLs; SQLAlchemy needs the
        explicit psycopg 3 driver. The URL is also parsed here so a typo fails at startup
        with a clear message instead of on the first query."""
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        for prefix in ("postgres://", "postgresql://"):
            if raw.startswith(prefix):
                raw = "postgresql+psycopg://" + raw[len(prefix):]
                break
        try:
            url = make_url(raw)
        except ArgumentError:
            raise ValueError("DATABASE_URL is not a valid database URL") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must be a PostgreSQL URL (postgresql://...)")
        if not url.host or not url.database:
            raise ValueError("DATABASE_URL must include a host and a database name")
        return SecretStr(raw)

    @field_validator("API_V1_PREFIX")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") or value.endswith("/") or " " in value:
            raise ValueError("API_V1_PREFIX must start with '/' and must not end with '/', e.g. /api/v1")
        return value

    @field_validator("FRONTEND_ORIGIN")
    @classmethod
    def _validate_origins(cls, value: str) -> str:
        origins = _split_origins(value)
        if not origins:
            raise ValueError("FRONTEND_ORIGIN must contain at least one origin")
        for origin in origins:
            if origin == "*":
                continue  # rejected in production below; allowed only for local experiments
            parts = urlsplit(origin)
            if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query:
                raise ValueError(
                    f"Invalid CORS origin {origin!r}: use scheme://host[:port] with no path, "
                    "e.g. http://localhost:5173"
                )
        return value

    @field_validator("LOG_LEVEL", "LOG_FORMAT", mode="before")
    @classmethod
    def _normalise_case(cls, value, info):
        if not isinstance(value, str):
            return value
        return value.upper() if info.field_name == "LOG_LEVEL" else value.lower()

    # --- Environment profiles ----------------------------------------------------
    @model_validator(mode="after")
    def _apply_environment_profile(self) -> "Settings":
        explicitly_set = self.model_fields_set
        if self.APP_ENV == "development":
            if "DEBUG" not in explicitly_set:
                self.DEBUG = True
            if "LOG_FORMAT" not in explicitly_set:
                self.LOG_FORMAT = "console"
            if "LOG_LEVEL" not in explicitly_set:
                self.LOG_LEVEL = "DEBUG"

        if self.is_production:
            problems = []
            if self.DEBUG:
                problems.append("DEBUG must be false")
            secret = self.JWT_SECRET_KEY.get_secret_value() if self.JWT_SECRET_KEY else ""
            if len(secret) < MIN_JWT_SECRET_LENGTH:
                problems.append(f"JWT_SECRET_KEY must be set and at least {MIN_JWT_SECRET_LENGTH} characters")
            if self.DATABASE_URL is None:
                problems.append("DATABASE_URL must be set")
            hash_key = self.IDENTIFIER_HASH_KEY.get_secret_value() if self.IDENTIFIER_HASH_KEY else ""
            if len(hash_key) < MIN_IDENTIFIER_HASH_KEY_LENGTH:
                problems.append(
                    f"IDENTIFIER_HASH_KEY must be set and at least {MIN_IDENTIFIER_HASH_KEY_LENGTH} characters"
                )
            if self.DB_ECHO:
                problems.append("DB_ECHO must be false (it would log query parameters)")
            for origin in self.cors_origins:
                if not origin.startswith("https://"):
                    problems.append(f"CORS origin {origin!r} must use https:// (no wildcards, no http)")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    # --- Derived values ------------------------------------------------------------
    @property
    def cors_origins(self) -> list[str]:
        return _split_origins(self.FRONTEND_ORIGIN)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs outside production only (P-1 security decision)."""
        return not self.is_production

    @property
    def database_configured(self) -> bool:
        return self.DATABASE_URL is not None

    @property
    def database_url_masked(self) -> str | None:
        """Database URL safe for logs: password replaced with ***."""
        if self.DATABASE_URL is None:
            return None
        return make_url(self.DATABASE_URL.get_secret_value()).render_as_string(hide_password=True)

    def safe_summary(self) -> dict[str, object]:
        """Non-secret configuration snapshot for the startup log."""
        return {
            "app_env": self.APP_ENV,
            "version": self.APP_VERSION,
            "debug": self.DEBUG,
            "api_prefix": self.API_V1_PREFIX,
            "cors_origins": self.cors_origins,
            "database": self.database_url_masked or "not configured",
            "jwt_secret_configured": self.JWT_SECRET_KEY is not None,
            "identifier_hash_key_configured": self.IDENTIFIER_HASH_KEY is not None,
            "docs_enabled": self.docs_enabled,
            "log_level": self.LOG_LEVEL,
        }


def _split_origins(value: str) -> list[str]:
    return [origin.strip().rstrip("/") for origin in value.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
