from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, SmallInteger, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.beneficiary import Beneficiary
    from app.models.transaction import Transaction


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An account holder. Never hard-deleted: deactivate with ``is_active = False``."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        UniqueConstraint("phone_number"),  # PostgreSQL allows many NULLs: optional but unique
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(r"email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'", name="email_format"),
        CheckConstraint("length(btrim(full_name)) > 0", name="full_name_not_blank"),
        CheckConstraint(r"phone_number ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        # Only Argon2id hashes are accepted, so a plaintext password can never be stored.
        CheckConstraint(
            "password_hash LIKE '$argon2id$%' AND length(password_hash) >= 50",
            name="password_hash_argon2id",
        ),
        CheckConstraint("failed_login_count BETWEEN 0 AND 100", name="failed_login_count_range"),
    )

    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    phone_number: Mapped[str | None] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    failed_login_count: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    beneficiaries: Mapped[list["Beneficiary"]] = relationship(back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="user")

    def __repr__(self) -> str:  # never include the password hash
        return f"<User id={self.id} email={self.email!r} active={self.is_active}>"
