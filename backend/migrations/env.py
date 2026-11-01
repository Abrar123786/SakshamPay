"""Alembic environment.

Target metadata is the shared ``Base.metadata``; importing ``app.models`` registers
all six P-4 tables on it.

Database URL, in order of precedence:
  1. a connection passed programmatically in ``config.attributes["connection"]``
     (used by the test suite to migrate a throwaway schema);
  2. ``DATABASE_URL`` from the environment or ``backend/.env`` (via Settings).
Credentials are never written to ``alembic.ini`` and never printed.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.config import get_settings
from app.database.base import Base

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

CONFIGURE_OPTIONS = {
    "target_metadata": target_metadata,
    "compare_type": True,
    "compare_server_default": True,
}


def _database_url() -> str:
    url = get_settings().DATABASE_URL
    if url is None:
        raise RuntimeError(
            "DATABASE_URL is not set. Add it to backend/.env (see .env.example) before running Alembic."
        )
    return url.get_secret_value()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (``alembic upgrade head --sql``)."""
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **CONFIGURE_OPTIONS,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection: Connection) -> None:
    context.configure(connection=connection, **CONFIGURE_OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided: Connection | None = config.attributes.get("connection")
    if provided is not None:
        _run_with_connection(provided)
        return
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _run_with_connection(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
