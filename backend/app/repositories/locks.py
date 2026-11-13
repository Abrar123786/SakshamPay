"""Transaction-scoped PostgreSQL advisory locks.

``pg_advisory_xact_lock`` is held until the surrounding database transaction commits
or rolls back, so a lock can never outlive the work it protects (and works with any
connection pooler). Keys are ``(namespace, hashtext(key))``: a hash collision between
two keys only makes two unrelated requests wait for each other briefly; it never
changes a result.

Lock order used by the services (never reversed, so no deadlock cycle can form):
  * payment creation: ``CREATE_PAYMENT`` (user) is the FIRST lock of its transaction;
  * verification: transaction row -> user row -> ``VERIFY_PREFIX`` (network) LAST;
  * login: ``LOGIN_PREFIX`` (network) first, then the user row (failed-login counter).
    Nothing that holds a user row ever waits for ``LOGIN_PREFIX``, so this is safe.
"""

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.exceptions import ServiceUnavailableError

CREATE_PAYMENT = 51_001  # key: user ID. Serialises the short creation transaction per user.
VERIFY_PREFIX = 51_002  # key: truncated network. Serialises counting + recording failures per network.
LOGIN_PREFIX = 51_003  # key: truncated network. The same for failed logins.

LOCK_TIMEOUT_MS = 2_000  # below DB_STATEMENT_TIMEOUT_MS, so a long wait fails as "busy", not as a timeout

LOCK_NOT_AVAILABLE = "55P03"


class BusyError(ServiceUnavailableError):
    code = "SERVICE_BUSY"
    message = "The service is busy with another request. Nothing was paid or changed. Please try again."


def advisory_xact_lock(session: Session, namespace: int, key: str, *, timeout_ms: int = LOCK_TIMEOUT_MS) -> None:
    """Wait (at most ``timeout_ms``) for the lock; raise BusyError if it is not granted.

    After a BusyError the database transaction is aborted: the caller must let the
    error propagate (the request session rolls back) or roll back itself.
    """
    session.execute(text("SELECT set_config('lock_timeout', :timeout, true)"), {"timeout": f"{int(timeout_ms)}ms"})
    try:
        session.execute(text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:key))"), {"namespace": namespace, "key": key})
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) == LOCK_NOT_AVAILABLE:
            raise BusyError() from None
        raise
    # Restore the session default (no lock timeout; the statement timeout still applies).
    session.execute(text("SELECT set_config('lock_timeout', '0', true)"))
