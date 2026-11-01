"""Shared repository plumbing.

Unit-of-work rule (P-3): repositories **flush, never commit**. The caller (a
service, the seed script, a test) owns the database transaction and decides to
``commit()`` or ``rollback()``, so several repository calls succeed or fail together.

``add()`` and ``flush()`` run each write inside a SAVEPOINT. A constraint violation therefore
rolls back only that write, is translated into a domain error, and leaves the
caller's surrounding transaction usable.
"""

from collections.abc import Callable, Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.repositories.errors import ConcurrentModificationError

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

ErrorFactory = Callable[[], Exception]


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the PostgreSQL constraint behind an IntegrityError (psycopg 3)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(int(limit), MAX_PAGE_SIZE))


def clamp_offset(offset: int | None) -> int:
    return max(0, int(offset or 0))


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, instance: object, translations: Mapping[str, ErrorFactory] | None = None) -> None:
        """Insert ``instance``. It is added *inside* the savepoint, so if the insert fails
        it is removed from the session again instead of being retried by the next flush."""
        self._flush_in_savepoint(translations, instance)

    def flush(self, translations: Mapping[str, ErrorFactory] | None = None) -> None:
        """Write pending changes to already-loaded objects (updates)."""
        self._flush_in_savepoint(translations)

    def _flush_in_savepoint(self, translations: Mapping[str, ErrorFactory] | None, new: object | None = None) -> None:
        """Flush pending changes in a savepoint, translating known failures.

        * unique/foreign-key violations named in ``translations`` -> domain errors
        * optimistic-lock conflicts (``version`` mismatch) -> ConcurrentModificationError
        * anything else propagates unchanged: a CHECK violation here means a bug in the
          caller, and must not be silently converted.
        """
        try:
            with self.session.begin_nested():
                if new is not None:
                    self.session.add(new)
                self.session.flush()
        except IntegrityError as exc:
            factory = (translations or {}).get(violated_constraint(exc) or "")
            if factory is not None:
                raise factory() from exc
            raise
        except StaleDataError as exc:
            raise ConcurrentModificationError() from exc
