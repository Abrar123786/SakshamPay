"""Centralised SQLAlchemy engine and session management.

One ``Database`` instance is created per application (``create_app``) from that
application's ``Settings`` and stored on ``app.state.database``.

* The engine is created lazily on first use, so the application starts, and
  ``/health`` answers, even when ``DATABASE_URL`` is not configured.
* ``check_connection()`` never raises; it reports a status for startup logs
  and the readiness endpoint.
* ``get_db`` is the FastAPI dependency that hands each request its own session.
* ``get_read_only_db`` hands a read-only endpoint a second, separate session whose
  transaction is REPEATABLE READ, READ ONLY from its first statement (P-9).
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.exceptions import DatabaseNotConfiguredError

logger = logging.getLogger("sakshampay.database")

ConnectionState = Literal["ok", "not_configured", "unavailable"]


@dataclass(frozen=True)
class DatabaseStatus:
    state: ConnectionState
    latency_ms: float | None = None
    error_type: str | None = None  # exception class name only; never the message


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def is_configured(self) -> bool:
        return self._settings.database_configured

    @property
    def engine(self) -> Engine:
        if self._settings.DATABASE_URL is None:
            raise DatabaseNotConfiguredError()
        if self._engine is None:
            s = self._settings
            self._engine = create_engine(
                s.DATABASE_URL.get_secret_value(),
                pool_pre_ping=True,  # replace connections dropped by the server or a restart
                pool_size=s.DB_POOL_SIZE,
                max_overflow=s.DB_MAX_OVERFLOW,
                pool_timeout=s.DB_POOL_TIMEOUT_SECONDS,
                pool_recycle=s.DB_POOL_RECYCLE_SECONDS,
                # SQL logging is controlled by DB_ECHO through the "sqlalchemy.engine"
                # logger (see core/logging.py); echo=True would add a second handler.
                echo=False,
                connect_args={
                    "connect_timeout": s.DB_CONNECT_TIMEOUT_SECONDS,
                    # timezone=UTC: psycopg returns TIMESTAMP WITH TIME ZONE values in the
                    # session time zone, which otherwise defaults to the server's setting
                    # (often the host's local zone). UTC makes every timestamp the application
                    # reads carry the same zone as the ones it creates; instants are unchanged.
                    "options": f"-c statement_timeout={s.DB_STATEMENT_TIMEOUT_MS} -c timezone=UTC",
                    "application_name": s.APP_NAME,
                },
            )
            logger.debug("Database engine created", extra={"database": s.database_url_masked})
        return self._engine

    def create_session(self) -> Session:
        if self._session_factory is None:
            self._session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        return self._session_factory()

    def check_connection(self) -> DatabaseStatus:
        """Run ``SELECT 1``. Safe to call when unconfigured or when the server is down."""
        if not self.is_configured:
            return DatabaseStatus(state="not_configured")
        started = time.perf_counter()
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            logger.warning(
                "Database connectivity check failed",
                extra={"exception_type": type(exc).__name__, "database": self._settings.database_url_masked},
            )
            return DatabaseStatus(state="unavailable", error_type=type(exc).__name__)
        return DatabaseStatus(state="ok", latency_ms=round((time.perf_counter() - started) * 1000, 1))

    def dispose(self) -> None:
        """Close pooled connections (application shutdown)."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            logger.info("Database connections closed")


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_db(database: Annotated[Database, Depends(get_database)]) -> Iterator[Session]:
    """FastAPI dependency: one session per request.

    Services own their transactions and call ``commit()`` explicitly. If the
    request fails, uncommitted work is rolled back; the session is always closed
    and its connection returned to the pool.
    """
    session = database.create_session()  # raises DatabaseNotConfiguredError (503) when unconfigured
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


# First statement of every read-only session's transaction. PostgreSQL accepts an
# isolation level only before any query in the transaction, so this statement also
# proves nothing ran before it; REPEATABLE READ gives all the request's queries one
# consistent snapshot, and READ ONLY makes PostgreSQL reject every write.
READ_ONLY_TRANSACTION = text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")


def get_read_only_db(database: Annotated[Database, Depends(get_database)]) -> Iterator[Session]:
    """FastAPI dependency: a separate, read-only session (P-9 dashboard).

    It is independent of the request's ``DbSession`` (which ``CurrentUser`` uses to
    load the user), so its transaction characteristics are set before any query in
    *its* transaction, whatever the authentication session has already run.

    Lifecycle: the session is created when the dependency is resolved (after
    ``CurrentUser`` when declared after it, so a request with a bad token never opens
    it), starts its transaction with ``READ_ONLY_TRANSACTION``, is never committed,
    and is closed when the request ends, on success or error. Closing ends the
    transaction with a rollback and returns the connection to the pool.
    """
    session = database.create_session()
    try:
        session.execute(READ_ONLY_TRANSACTION)
        yield session
    finally:
        session.close()


ReadOnlyDbSession = Annotated[Session, Depends(get_read_only_db)]
