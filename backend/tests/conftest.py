import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

FRONTEND = "http://localhost:5173"
# Nothing listens on port 1: connections are refused immediately, which lets us test
# "database configured but unreachable" without a PostgreSQL server.
UNREACHABLE_DATABASE_URL = "postgresql://sakshampay:not-a-real-password@127.0.0.1:1/sakshampay"
PRODUCTION_SECRET = "p" * 48


def make_settings(**overrides) -> Settings:
    """Settings isolated from the developer's .env and environment."""
    values = {"APP_ENV": "test", "FRONTEND_ORIGIN": FRONTEND, "LOG_FORMAT": "json"}
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_production_settings(**overrides) -> Settings:
    values = {
        "APP_ENV": "production",
        "JWT_SECRET_KEY": PRODUCTION_SECRET,
        "DATABASE_URL": UNREACHABLE_DATABASE_URL,
        "FRONTEND_ORIGIN": "https://sakshampay.example",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    # raise_server_exceptions=False lets tests assert on the 500 response body.
    # The context manager runs the lifespan (startup and shutdown).
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def unreachable_db_client():
    app = create_app(make_settings(DATABASE_URL=UNREACHABLE_DATABASE_URL, DB_CONNECT_TIMEOUT_SECONDS=1))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def real_database_url() -> str:
    """Integration tests run only when TEST_DATABASE_URL points at a disposable database."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; skipping PostgreSQL integration test")
    return url
