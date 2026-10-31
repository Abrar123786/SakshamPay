"""Database infrastructure: lazy engine, connectivity check, session dependency.

Everything except the last test runs without PostgreSQL. The integration test runs
only when TEST_DATABASE_URL points at a disposable database.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import DatabaseNotConfiguredError, register_exception_handlers
from app.database.session import Database, DbSession, get_database
from app.main import create_app
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings


def configured_database(**overrides) -> Database:
    return Database(make_settings(DATABASE_URL=UNREACHABLE_DATABASE_URL, DB_CONNECT_TIMEOUT_SECONDS=1, **overrides))


# --- unconfigured ----------------------------------------------------------------

def test_unconfigured_database_reports_not_configured():
    database = Database(make_settings())
    assert not database.is_configured
    assert database.check_connection().state == "not_configured"


def test_unconfigured_database_refuses_sessions():
    with pytest.raises(DatabaseNotConfiguredError):
        Database(make_settings()).create_session()


# --- engine configuration (no connection is made) -----------------------------------

def test_engine_is_created_lazily_and_reused():
    database = configured_database()
    assert database._engine is None
    assert database.engine is database.engine


def test_engine_uses_settings():
    engine = configured_database(DB_POOL_SIZE=7, DB_MAX_OVERFLOW=3, DB_POOL_TIMEOUT_SECONDS=9).engine
    assert engine.pool.size() == 7
    assert engine.pool._max_overflow == 3
    assert engine.pool._timeout == 9
    assert engine.dialect.driver == "psycopg"
    assert engine.url.password == "not-a-real-password"  # kept in memory, never logged


def test_unreachable_database_reports_unavailable_without_raising():
    status = configured_database().check_connection()
    assert status.state == "unavailable"
    assert status.error_type == "OperationalError"


def test_dispose_releases_engine():
    database = configured_database()
    _ = database.engine
    database.dispose()
    assert database._engine is None


# --- request dependency ---------------------------------------------------------------

class FakeSession:
    def __init__(self):
        self.rolled_back = False
        self.closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class FakeDatabase:
    def __init__(self):
        self.sessions: list[FakeSession] = []

    def create_session(self):
        session = FakeSession()
        self.sessions.append(session)
        return session


def app_with_session_route(database) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_database] = lambda: database

    @app.get("/uses-db")
    def uses_db(session: DbSession):
        return {"session": type(session).__name__}

    @app.get("/fails")
    def fails(session: DbSession):
        raise RuntimeError("boom")

    return app


def test_get_db_yields_a_session_and_closes_it():
    database = FakeDatabase()
    with TestClient(app_with_session_route(database)) as client:
        assert client.get("/uses-db").json() == {"session": "FakeSession"}
    assert database.sessions[0].closed and not database.sessions[0].rolled_back


def test_get_db_rolls_back_and_closes_on_error():
    database = FakeDatabase()
    with TestClient(app_with_session_route(database), raise_server_exceptions=False) as client:
        assert client.get("/fails").status_code == 500
    assert database.sessions[0].rolled_back and database.sessions[0].closed


def test_session_dependency_returns_503_when_database_not_configured():
    app = create_app(make_settings())

    @app.get("/_test/needs-db")
    def needs_db(session: DbSession):
        return {}

    with TestClient(app) as client:
        response = client.get("/_test/needs-db")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_NOT_CONFIGURED"


def test_session_dependency_returns_503_when_database_unreachable(unreachable_db_client):
    app = unreachable_db_client.app

    @app.get("/_test/query")
    def query(session: DbSession):
        return {"value": session.execute(text("SELECT 1")).scalar()}

    response = unreachable_db_client.get("/_test/query")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


# --- real PostgreSQL (optional) --------------------------------------------------------

def test_real_postgresql_session_and_readiness(real_database_url):
    app = create_app(make_settings(DATABASE_URL=real_database_url))

    @app.get("/_test/query")
    def query(session: DbSession):
        assert isinstance(session, Session)
        return {
            "value": session.execute(text("SELECT 1")).scalar(),
            "statement_timeout": session.execute(text("SHOW statement_timeout")).scalar(),
        }

    with TestClient(app) as client:
        assert client.get("/_test/query").json() == {"value": 1, "statement_timeout": "3s"}
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"]["database"]["status"] == "ok"
