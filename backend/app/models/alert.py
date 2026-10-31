import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.models.common import CreatedAtMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AlertSeverity, AlertType

if TYPE_CHECKING:
    from app.models.risk_assessment import RiskAssessment
    from app.models.transaction import Transaction
    from app.models.user import User


class Alert(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """An in-app notification for one user, optionally about a transaction and its assessment.

    Composite foreign keys guarantee the linked transaction belongs to the same user
    and the linked assessment belongs to the linked transaction.
    """

    __tablename__ = "alerts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["risk_assessment_id", "transaction_id"],
            ["risk_assessments.id", "risk_assessments.transaction_id"],
            ondelete="RESTRICT",
        ),
        # Composite FKs are skipped when any column is NULL, so an assessment link
        # requires the transaction link too.
        CheckConstraint(
            "risk_assessment_id IS NULL OR transaction_id IS NOT NULL", name="assessment_requires_transaction"
        ),
        CheckConstraint("is_read = (read_at IS NOT NULL)", name="read_at_matches_is_read"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("length(btrim(message)) > 0", name="message_not_blank"),
        Index("ix_alerts_user_id_is_read_created_at", "user_id", "is_read", "created_at"),
        Index("ix_alerts_transaction_id", "transaction_id"),
        Index("ix_alerts_risk_assessment_id", "risk_assessment_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"))
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    alert_type: Mapped[AlertType] = mapped_column(enum_column(AlertType, "alert_type", 32))
    severity: Mapped[AlertSeverity] = mapped_column(enum_column(AlertSeverity, "severity", 16))
    title: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="alerts")
    transaction: Mapped["Transaction | None"] = relationship(
        back_populates="alerts",
        primaryjoin="foreign(Alert.transaction_id) == Transaction.id",
    )
    risk_assessment: Mapped["RiskAssessment | None"] = relationship(
        back_populates="alerts",
        primaryjoin="foreign(Alert.risk_assessment_id) == RiskAssessment.id",
    )

    def __repr__(self) -> str:
        return f"<Alert id={self.id} type={self.alert_type} read={self.is_read}>"
