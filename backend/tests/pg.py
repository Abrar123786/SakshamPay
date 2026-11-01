"""PostgreSQL test support (P-5).

Every PostgreSQL test database is built the production way: ``alembic upgrade head``
into a throwaway schema, which is dropped afterwards. Nothing touches the schema the
developer works in, so TEST_DATABASE_URL may point at the development database.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.migrations import alembic_config
from app.database.session import Database
from tests.conftest import make_settings

TEST_IDENTIFIER_KEY = "test-identifier-key-0123456789abcdef"


def require_postgres_url() -> str:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL not set; skipping PostgreSQL tests", allow_module_level=True)
    return Settings(_env_file=None, APP_ENV="test", DATABASE_URL=raw).DATABASE_URL.get_secret_value()


def run_alembic(engine: Engine, action: str, revision: str) -> None:
    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        config.attributes["configure_logger"] = False
        getattr(command, action)(config, revision)


@contextmanager
def throwaway_schema(url: str, *, migrate: bool = True) -> Iterator[Engine]:
    schema = f"p5_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    try:
        if migrate:
            run_alembic(engine, "upgrade", "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@contextmanager
def rollback_session(engine: Engine) -> Iterator[Session]:
    """Session whose commits are savepoints inside one outer transaction that is
    rolled back at the end, so each test leaves the schema untouched."""
    connection = engine.connect()
    outer = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


def database_for(engine: Engine, **settings_overrides) -> Database:
    """A P-3 ``Database`` that uses the given engine (and therefore its schema)."""
    database = Database(make_settings(DATABASE_URL=str(engine.url.render_as_string(hide_password=False)), **settings_overrides))
    database._engine = engine
    return database


def settings_for(url: str, **overrides) -> Settings:
    return make_settings(DATABASE_URL=url, IDENTIFIER_HASH_KEY=TEST_IDENTIFIER_KEY, **overrides)
