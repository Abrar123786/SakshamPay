import pytest
from pydantic import ValidationError

from app.core.config import Settings


def make(**overrides):
    return Settings(_env_file=None, **overrides)


def test_defaults_are_development_safe():
    s = make()
    assert s.APP_NAME == "SakshamPay"
    assert s.APP_VERSION == "1.0.0"
    assert s.JWT_ALGORITHM == "HS256"
    assert s.ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert s.DATABASE_URL is None
    assert s.docs_enabled


@pytest.mark.parametrize(
    "raw",
    ["postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d", "postgresql+psycopg://u:p@h:5432/d"],
)
def test_database_url_is_normalised_to_psycopg3(raw):
    assert make(DATABASE_URL=raw).DATABASE_URL == "postgresql+psycopg://u:p@h:5432/d"


def test_empty_strings_from_env_example_mean_unset():
    s = make(DATABASE_URL="", JWT_SECRET_KEY="")
    assert s.DATABASE_URL is None and s.JWT_SECRET_KEY is None


def test_multiple_cors_origins_are_parsed():
    s = make(FRONTEND_ORIGIN="http://localhost:5173, https://sakshampay.vercel.app/")
    assert s.cors_origins == ["http://localhost:5173", "https://sakshampay.vercel.app"]


def test_production_requires_strong_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        make(APP_ENV="production", JWT_SECRET_KEY="too-short")


def test_production_rejects_debug():
    with pytest.raises(ValidationError, match="DEBUG"):
        make(APP_ENV="production", DEBUG=True, JWT_SECRET_KEY="x" * 40)


def test_production_disables_api_docs():
    s = make(APP_ENV="production", JWT_SECRET_KEY="x" * 40)
    assert not s.docs_enabled


def test_secret_is_not_exposed_in_repr():
    s = make(JWT_SECRET_KEY="x" * 40)
    assert "x" * 40 not in repr(s)
