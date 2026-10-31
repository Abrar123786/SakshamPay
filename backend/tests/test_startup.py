"""Application startup and shutdown (lifespan) behaviour."""

import logging

from fastapi.testclient import TestClient

from app.database.session import Database
from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings


def test_app_starts_and_exposes_settings_and_database(client, app, settings):
    assert app.state.settings is settings
    assert isinstance(app.state.database, Database)
    assert client.get("/health").status_code == 200


def test_startup_without_database_logs_warning_and_keeps_serving(caplog, settings):
    caplog.set_level(logging.INFO)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    messages = [r.getMessage() for r in caplog.records]
    assert "Starting application" in messages
    assert any("DATABASE_URL is not set" in m for m in messages)
    assert "Application stopped" in messages


def test_startup_with_unreachable_database_does_not_crash(caplog):
    caplog.set_level(logging.INFO)
    app = create_app(make_settings(DATABASE_URL=UNREACHABLE_DATABASE_URL, DB_CONNECT_TIMEOUT_SECONDS=1))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert any("unreachable" in r.getMessage() for r in caplog.records)


def test_startup_log_contains_no_secrets(caplog):
    caplog.set_level(logging.INFO)
    secret = "s" * 40
    app = create_app(
        make_settings(DATABASE_URL=UNREACHABLE_DATABASE_URL, JWT_SECRET_KEY=secret, DB_CONNECT_TIMEOUT_SECONDS=1)
    )
    with TestClient(app):
        pass
    logged = caplog.text + " ".join(str(r.__dict__) for r in caplog.records)
    assert secret not in logged
    assert "not-a-real-password" not in logged
    start = next(r for r in caplog.records if r.getMessage() == "Starting application")
    assert start.database == "postgresql+psycopg://sakshampay:***@127.0.0.1:1/sakshampay"
    assert start.jwt_secret_configured is True


def test_shutdown_disposes_database_engine():
    app = create_app(make_settings(DATABASE_URL=UNREACHABLE_DATABASE_URL, DB_CONNECT_TIMEOUT_SECONDS=1))
    with TestClient(app):
        assert app.state.database._engine is not None  # created by the startup connectivity check
    assert app.state.database._engine is None
