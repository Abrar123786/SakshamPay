import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.models import Alert, AlertSeverity, AlertType
from app.repositories.base import Repository, clamp_limit, clamp_offset
from app.repositories.errors import AlertNotFoundError, TransactionNotFoundError


class AlertRepository(Repository):
    """In-app alerts. Every read and write is scoped to the owning user."""

    def create(
        self,
        *,
        user_id: uuid.UUID,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        transaction_id: uuid.UUID | None = None,
        risk_assessment_id: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ) -> Alert:
        """``created_at`` is for imports and seed data; normally the database clock is used."""
        alert = Alert(
            user_id=user_id,
            alert_type=alert_type,
            severity=severity,
            title=title.strip(),
            message=message.strip(),
            transaction_id=transaction_id,
            risk_assessment_id=risk_assessment_id,
        )
        if created_at is not None:
            alert.created_at = created_at
        # Composite FKs: the transaction must be the user's, the assessment must be the transaction's.
        self.add(
            alert,
            {
                "fk_alerts_transaction_id_user_id_transactions": TransactionNotFoundError,
                "fk_alerts_risk_assessment_id_transaction_id_risk_assessments": TransactionNotFoundError,
            }
        )
        return alert

    def list_for_user(
        self, user_id: uuid.UUID, *, unread_only: bool = False, limit: int | None = None, offset: int | None = None
    ) -> list[Alert]:
        query = select(Alert).where(Alert.user_id == user_id)
        if unread_only:
            query = query.where(Alert.is_read.is_(False))
        query = query.order_by(Alert.created_at.desc(), Alert.id).limit(clamp_limit(limit)).offset(clamp_offset(offset))
        return list(self.session.scalars(query))

    def list_unread(self, user_id: uuid.UUID, *, limit: int | None = None) -> list[Alert]:
        return self.list_for_user(user_id, unread_only=True, limit=limit)

    def count_unread(self, user_id: uuid.UUID) -> int:
        return self.session.scalar(
            select(func.count()).select_from(Alert).where(Alert.user_id == user_id, Alert.is_read.is_(False))
        )

    def mark_read(self, alert_id: uuid.UUID, user_id: uuid.UUID, *, at: datetime | None = None) -> Alert:
        """Idempotent: an already-read alert keeps its original read time."""
        alert = self.session.scalar(select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id))
        if alert is None:
            raise AlertNotFoundError()
        if not alert.is_read:
            alert.is_read = True
            alert.read_at = at or datetime.now(UTC)
            self.flush()
        return alert

    def mark_all_read(self, user_id: uuid.UUID, *, at: datetime | None = None) -> int:
        """Returns how many alerts changed."""
        result = self.session.execute(
            update(Alert)
            .where(Alert.user_id == user_id, Alert.is_read.is_(False))
            .values(is_read=True, read_at=at or datetime.now(UTC))
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount
