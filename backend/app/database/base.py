"""Declarative base shared by every ORM model (``app/models``).

The naming convention gives every constraint and index a predictable name,
which keeps Alembic migrations stable and reviewable. Multi-column constraints
include every column name (``column_0_N_name``) so, for example, the composite
unique keys ``(user_id, idempotency_key)`` and ``(id, user_id)`` on one table
cannot collide.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
