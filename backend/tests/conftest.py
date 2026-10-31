import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

FRONTEND = "http://localhost:5173"


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never depend on a developer's local .env
    return Settings(_env_file=None, APP_ENV="test", DEBUG=False, FRONTEND_ORIGIN=FRONTEND, LOG_FORMAT="json")


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    # raise_server_exceptions=False lets us assert on the 500 response body
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
