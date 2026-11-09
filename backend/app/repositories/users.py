import uuid
from datetime import datetime, timedelta

from sqlalchemy import case, select, update

from app.models import User
from app.repositories.base import Repository
from app.repositories.errors import EmailAlreadyRegisteredError, PhoneAlreadyRegisteredError

_UNSET = object()


def normalise_email(email: str) -> str:
    return email.strip().lower()


class UserRepository(Repository):
    """User records. Users are deactivated, never deleted.

    Password hashing is not done here (P-6): ``password_hash`` must already be an
    Argon2id hash, and the database rejects anything else.
    """

    _translations = {
        "uq_users_email": EmailAlreadyRegisteredError,
        "uq_users_phone_number": PhoneAlreadyRegisteredError,
    }

    def create(
        self, *, full_name: str, email: str, password_hash: str, phone_number: str | None = None
    ) -> User:
        user = User(
            full_name=full_name.strip(),
            email=normalise_email(email),
            password_hash=password_hash,
            phone_number=phone_number,
        )
        self.add(user, self._translations)
        return user

    def get(self, user_id: uuid.UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        return self.session.scalar(select(User).where(User.email == normalise_email(email)))

    def update_details(self, user: User, *, full_name=_UNSET, phone_number=_UNSET) -> User:
        """Change profile fields only; email and password changes belong to P-6 flows."""
        if full_name is not _UNSET:
            user.full_name = full_name.strip()
        if phone_number is not _UNSET:
            user.phone_number = phone_number
        self.flush(self._translations)
        return user

    def deactivate(self, user: User) -> User:
        user.is_active = False
        self.flush()
        return user

    # ---- login bookkeeping (P-6) ------------------------------------------------------------

    def record_failed_login(self, user: User, *, now: datetime, max_attempts: int, lockout: timedelta) -> bool:
        """Count a failed login atomically; lock the account when the limit is reached.

        Returns True if this failure locked the account. A single UPDATE does the
        read-increment-write, so concurrent failures cannot lose a count. The counter
        restarts at 0 when the lock is applied.
        """
        reaches_limit = User.failed_login_count + 1 >= max_attempts
        locked_until = self.session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                failed_login_count=case((reaches_limit, 0), else_=User.failed_login_count + 1),
                locked_until=case((reaches_limit, now + lockout), else_=User.locked_until),
            )
            .returning(User.locked_until)
            .execution_options(synchronize_session=False)
        ).scalar_one()
        self.session.expire(user, ["failed_login_count", "locked_until", "updated_at"])
        return locked_until is not None and locked_until > now

    def record_successful_login(self, user: User, *, now: datetime) -> User:
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        self.flush()
        return user

    def set_password_hash(self, user: User, password_hash: str) -> User:
        """Replace the stored hash (used to upgrade hashing parameters on login)."""
        user.password_hash = password_hash
        self.flush()
        return user
