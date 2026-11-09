import uuid

from sqlalchemy import select

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
