"""Alembic helpers usable from application code, scripts and tests."""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection

from app.core.config import BACKEND_DIR

ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config(ini_path: Path = ALEMBIC_INI) -> Config:
    config = Config(str(ini_path))
    config.set_main_option("script_location", str(ini_path.parent / "migrations"))
    return config


def head_revision() -> str:
    """Latest migration revision shipped with the code."""
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(connection: Connection) -> str | None:
    """Revision recorded in the database (None when no migration has run)."""
    return MigrationContext.configure(connection).get_current_revision()


def is_up_to_date(connection: Connection) -> bool:
    return current_revision(connection) == head_revision()
