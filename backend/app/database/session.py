"""Database engine and session management.

The engine is created lazily on first use, so the application (and /health)
starts even when DATABASE_URL is not configured yet.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError

CONNECT_TIMEOUT_SECONDS = 5
STATEMENT_TIMEOUT_MS = 3000


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if not settings.DATABASE_URL:
        raise ServiceUnavailableError("The database is not configured.", code="DATABASE_NOT_CONFIGURED")
    return create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,  # drop dead connections (e.g. after the host restarts)
        pool_size=5,
        max_overflow=5,
        connect_args={
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        },
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
