"""Centralised configuration: profiles, validation and secret handling."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.conftest import PRODUCTION_SECRET, UNREACHABLE_DATABASE_URL, make_production_settings


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# --- defaults and profiles ------------------------------------------------------

def test_core_defaults():
    s = make()
    assert (s.APP_NAME, s.APP_VERSION, s.API_V1_PREFIX) == ("SakshamPay", "1.0.0", "/api/v1")
    assert (s.JWT_ALGORITHM, s.ACCESS_TOKEN_EXPIRE_MINUTES) == ("HS256", 30)
    assert s.DATABASE_URL is None and not s.database_configured


def test_development_profile_defaults():
    s = make(APP_ENV="development")
    assert s.DEBUG is True
    assert s.LOG_FORMAT == "console"
    assert s.LOG_LEVEL == "DEBUG"
    assert s.docs_enabled


def test_explicit_values_override_the_profile():
    s = make(APP_ENV="development", DEBUG=False, LOG_FORMAT="json", LOG_LEVEL="warning")
    assert (s.DEBUG, s.LOG_FORMAT, s.LOG_LEVEL) == (False, "json", "WARNING")


def test_test_profile_defaults():
    s = make(APP_ENV="test")
    assert (s.DEBUG, s.LOG_FORMAT, s.LOG_LEVEL) == (False, "json", "INFO")


def test_valid_production_configuration():
    s = make_production_settings()
    assert s.is_production and not s.DEBUG and not s.docs_enabled


# --- production guard-rails -------------------------------------------------------

@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"DEBUG": True}, "DEBUG must be false"),
        ({"JWT_SECRET_KEY": "short"}, "JWT_SECRET_KEY"),
        ({"JWT_SECRET_KEY": ""}, "JWT_SECRET_KEY"),
        ({"DATABASE_URL": ""}, "DATABASE_URL must be set"),
        ({"DB_ECHO": True}, "DB_ECHO"),
        ({"FRONTEND_ORIGIN": "http://sakshampay.example"}, "https://"),
        ({"FRONTEND_ORIGIN": "*"}, "https://"),
    ],
)
def test_production_rejects_unsafe_settings(override, problem):
    with pytest.raises(ValidationError, match="Unsafe production configuration") as exc_info:
        make_production_settings(**override)
    assert problem in str(exc_info.value)


# --- database URL ------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw", ["postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"]
)
def test_database_url_is_normalised_to_psycopg3(raw):
    assert make(DATABASE_URL=raw).DATABASE_URL.get_secret_value() == "postgresql+psycopg://u:p@h:5432/d"


@pytest.mark.parametrize(
    "raw", ["not a url", "mysql://u:p@h:3306/d", "sqlite:///local.db", "postgresql://u:p@h:5432"]
)
def test_invalid_database_urls_fail_at_startup(raw):
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        make(DATABASE_URL=raw)


def test_blank_values_from_env_example_mean_unset():
    s = make(DATABASE_URL="  ", JWT_SECRET_KEY="")
    assert s.DATABASE_URL is None and s.JWT_SECRET_KEY is None


# --- CORS and prefix ---------------------------------------------------------------

def test_multiple_cors_origins_are_parsed():
    s = make(FRONTEND_ORIGIN="http://localhost:5173, https://sakshampay.vercel.app/")
    assert s.cors_origins == ["http://localhost:5173", "https://sakshampay.vercel.app"]


@pytest.mark.parametrize("origin", ["localhost:5173", "http://localhost:5173/app", "ftp://x.example", ""])
def test_malformed_cors_origins_are_rejected(origin):
    with pytest.raises(ValidationError, match="origin"):
        make(FRONTEND_ORIGIN=origin)


@pytest.mark.parametrize("prefix", ["api/v1", "/api/v1/", "/api v1"])
def test_malformed_api_prefix_is_rejected(prefix):
    with pytest.raises(ValidationError, match="API_V1_PREFIX"):
        make(API_V1_PREFIX=prefix)


# --- secrets -----------------------------------------------------------------------

def test_secrets_never_appear_in_repr_or_summary():
    s = make(DATABASE_URL=UNREACHABLE_DATABASE_URL, JWT_SECRET_KEY=PRODUCTION_SECRET)
    rendered = repr(s) + str(s.safe_summary())
    assert PRODUCTION_SECRET not in rendered
    assert "not-a-real-password" not in rendered
    assert s.database_url_masked == "postgresql+psycopg://sakshampay:***@127.0.0.1:1/sakshampay"


def test_settings_are_loaded_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=SakshamPay-Local\nACCESS_TOKEN_EXPIRE_MINUTES=15\n")
    s = Settings(_env_file=env_file)
    assert s.APP_NAME == "SakshamPay-Local" and s.ACCESS_TOKEN_EXPIRE_MINUTES == 15
