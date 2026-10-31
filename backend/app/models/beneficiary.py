import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR

from app.database.base import Base
from app.models.common import HEX64_PATTERN, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class Beneficiary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A payee saved by a user. Fictional payees only: no bank or UPI integration.

    Account references and UPI IDs are sensitive, so the raw values are never stored:
    ``*_masked`` is what the UI shows, ``*_fingerprint`` (HMAC-SHA256 with a server
    key, computed by the service layer) detects duplicates and repeat payees.
    Deactivate with ``is_active = False``; transactions keep referencing the row.
    """

    __tablename__ = "beneficiaries"
    __table_args__ = (
        UniqueConstraint("user_id", "account_reference_fingerprint"),
        UniqueConstraint("user_id", "upi_id_fingerprint"),
        # Target of the ownership foreign key from transactions (beneficiary_id, user_id).
        UniqueConstraint("id", "user_id"),
        CheckConstraint(
            "account_reference_fingerprint IS NOT NULL OR upi_id_fingerprint IS NOT NULL",
            name="has_payment_identifier",
        ),
        CheckConstraint(
            "(account_reference_masked IS NULL) = (account_reference_fingerprint IS NULL)",
            name="account_reference_pair",
        ),
        CheckConstraint("(upi_id_masked IS NULL) = (upi_id_fingerprint IS NULL)", name="upi_id_pair"),
        CheckConstraint(f"account_reference_fingerprint ~ '{HEX64_PATTERN}'", name="account_fingerprint_hex"),
        CheckConstraint(f"upi_id_fingerprint ~ '{HEX64_PATTERN}'", name="upi_fingerprint_hex"),
        CheckConstraint("length(btrim(beneficiary_name)) > 0", name="name_not_blank"),
        Index("ix_beneficiaries_user_id_created_at", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    beneficiary_name: Mapped[str] = mapped_column(String(100))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    account_reference_masked: Mapped[str | None] = mapped_column(String(34))
    account_reference_fingerprint: Mapped[str | None] = mapped_column(CHAR(64))
    upi_id_masked: Mapped[str | None] = mapped_column(String(100))
    upi_id_fingerprint: Mapped[str | None] = mapped_column(CHAR(64))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))

    user: Mapped["User"] = relationship(back_populates="beneficiaries")
    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="beneficiary",
        primaryjoin="Beneficiary.id == foreign(Transaction.beneficiary_id)",
    )

    def __repr__(self) -> str:
        return f"<Beneficiary id={self.id} name={self.beneficiary_name!r} active={self.is_active}>"
