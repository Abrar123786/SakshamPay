import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR

from app.database.base import Base
from app.models.common import HEX64_PATTERN, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import (
    TERMINAL_TRANSACTION_STATUSES,
    ApprovalMethod,
    TransactionStatus,
    TransactionType,
)

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.beneficiary import Beneficiary
    from app.models.risk_assessment import RiskAssessment
    from app.models.user import User


def _sql_in(statuses) -> str:
    return ", ".join(f"'{s.value}'" for s in sorted(statuses, key=lambda s: s.value))


_TERMINAL = _sql_in(TERMINAL_TRANSACTION_STATUSES)
# Every state that can only be reached after a stored risk assessment.
_ASSESSED = _sql_in(
    {
        TransactionStatus.ANALYSED,
        TransactionStatus.AWAITING_USER_ACTION,
        TransactionStatus.APPROVED,
        TransactionStatus.CANCELLED,
        TransactionStatus.EXPIRED,
    }
)

MAX_VERIFY_ATTEMPTS = 3


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One simulated payment attempt and its P-1 lifecycle state.

    Money is ``amount_paise`` (integer paise, BIGINT): Rs 1,234.50 is 123450.
    Rows are never deleted. ``version`` is an optimistic-lock counter maintained
    by SQLAlchemy, so two concurrent state changes cannot both succeed.
    """

    __tablename__ = "transactions"
    __table_args__ = (
        # The beneficiary must belong to the same user. This composite key is the only
        # foreign key on beneficiary_id: it implies beneficiary_id -> beneficiaries.id.
        ForeignKeyConstraint(
            ["beneficiary_id", "user_id"],
            ["beneficiaries.id", "beneficiaries.user_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("id", "user_id"),  # target of the ownership FK from alerts
        CheckConstraint("amount_paise > 0", name="amount_positive"),
        CheckConstraint("currency = 'INR'", name="currency_inr"),
        CheckConstraint("length(idempotency_key) BETWEEN 8 AND 128", name="idempotency_key_length"),
        CheckConstraint(f"request_hash ~ '{HEX64_PATTERN}'", name="request_hash_hex"),
        CheckConstraint(f"device_id_hash ~ '{HEX64_PATTERN}'", name="device_id_hash_hex"),
        CheckConstraint(f"verify_attempts BETWEEN 0 AND {MAX_VERIFY_ATTEMPTS}", name="verify_attempts_range"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(f"status NOT IN ({_ASSESSED}) OR analysed_at IS NOT NULL", name="analysed_at_required"),
        CheckConstraint(f"(status IN ({_TERMINAL})) = (completed_at IS NOT NULL)", name="completed_at_matches_status"),
        CheckConstraint(
            "(status = 'APPROVED') = (approval_method IS NOT NULL)", name="approval_method_matches_status"
        ),
        CheckConstraint(
            "status <> 'AWAITING_USER_ACTION' OR expires_at IS NOT NULL", name="expires_at_required"
        ),
        CheckConstraint(
            "(analysed_at IS NULL OR analysed_at >= initiated_at)"
            " AND (completed_at IS NULL OR completed_at >= initiated_at)"
            " AND (completed_at IS NULL OR analysed_at IS NULL OR completed_at >= analysed_at)",
            name="timestamps_ordered",
        ),
        Index("ix_transactions_user_id_created_at", "user_id", "created_at"),
        Index("ix_transactions_beneficiary_id_created_at", "beneficiary_id", "created_at"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_created_at", "created_at"),
        Index(
            "ix_transactions_awaiting_expires_at",
            "expires_at",
            postgresql_where=text("status = 'AWAITING_USER_ACTION'"),
        ),
        Index(
            "ix_transactions_initiated_initiated_at",
            "initiated_at",
            postgresql_where=text("status = 'INITIATED'"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    beneficiary_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3), default="INR", server_default=text("'INR'"))
    transaction_type: Mapped[TransactionType] = mapped_column(enum_column(TransactionType, "transaction_type", 16))
    status: Mapped[TransactionStatus] = mapped_column(
        enum_column(TransactionStatus, "status", 32),
        default=TransactionStatus.INITIATED,
        server_default=text(f"'{TransactionStatus.INITIATED.value}'"),
    )
    description: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(CHAR(64))
    device_id_hash: Mapped[str | None] = mapped_column(CHAR(64))
    approval_method: Mapped[ApprovalMethod | None] = mapped_column(enum_column(ApprovalMethod, "approval_method", 16))
    verify_attempts: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    version: Mapped[int] = mapped_column(Integer)

    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {"version_id_col": version}

    user: Mapped["User"] = relationship(back_populates="transactions")
    beneficiary: Mapped["Beneficiary"] = relationship(
        back_populates="transactions",
        primaryjoin="foreign(Transaction.beneficiary_id) == Beneficiary.id",
    )
    risk_assessment: Mapped["RiskAssessment | None"] = relationship(back_populates="transaction", uselist=False)
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="transaction",
        primaryjoin="Transaction.id == foreign(Alert.transaction_id)",
    )

    def __repr__(self) -> str:
        return f"<Transaction id={self.id} status={self.status} amount_paise={self.amount_paise}>"
