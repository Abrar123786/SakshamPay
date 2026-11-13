"""Types shared by the API's response models.

Timestamps
----------
Every timestamp the API returns is serialised in UTC with a ``Z`` suffix, e.g.
``2026-11-13T11:59:57.827761Z``, whatever time zone the value carried inside the
application. The instant and its microseconds are never changed, only the zone it is
written in. (Pydantic omits the fraction when the microseconds are exactly zero:
``2026-11-13T11:59:57Z``.)

Why this is needed: PostgreSQL stores ``TIMESTAMP WITH TIME ZONE`` as an instant, and
psycopg returns it in the *session* time zone (the server's ``TimeZone`` setting
unless the connection sets one). Values created in Python are UTC. Without this type
one response could mix ``Z`` and ``+05:30`` for the same kind of field, and a value
read back from the database (an idempotent replay, a repeated action) would be
written differently from the same value in the original response. The database
connection also sets ``timezone=UTC`` (``app.database.session``); this type keeps the
API correct even when a value reaches it some other way.
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def as_utc(value: datetime) -> datetime:
    """The same instant in UTC. Naive datetimes are rejected: their instant is unknown."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("API timestamps must be timezone-aware")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(as_utc)]
