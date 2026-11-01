import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.models import RiskAssessment, RiskLevel, Transaction, TransactionStatus, compute_final_risk_score
from app.repositories.base import Repository, clamp_limit, clamp_offset
from app.repositories.errors import AssessmentAlreadyExistsError, InvalidStateTransitionError


class RiskAssessmentRepository(Repository):
    """Immutable assessment records: create and read only (no update, no delete).

    The final score is always computed here with the approved formula
    (``compute_final_risk_score``), never accepted from the caller, so stored rows
    cannot disagree with the formula (the database checks it as well).

    History: P-4 stores one assessment per transaction, so "assessment history"
    means a user's assessments across their transactions (``list_for_user``),
    not several versions for one transaction.
    """

    def create(
        self,
        transaction: Transaction,
        *,
        rule_score: int,
        ml_score: int | None,
        risk_level: RiskLevel,
        config_version: str,
        rule_details: list[dict[str, Any]],
        explanation: list[dict[str, Any]],
        features_snapshot: dict[str, Any],
        allowed_actions: list[str],
        model_version: str | None = None,
        ml_details: dict[str, Any] | None = None,
        assessed_at: datetime | None = None,
    ) -> RiskAssessment:
        """Store the assessment of a transaction that is still INITIATED (P-1: the
        assessment is stored first, then the transaction moves to ANALYSED).

        ``assessed_at`` is for imports and seed data; normally the database clock is used."""
        if transaction.status != TransactionStatus.INITIATED:
            raise InvalidStateTransitionError("Only an INITIATED transaction can be assessed.")
        assessment = RiskAssessment(
            transaction_id=transaction.id,
            rule_score=rule_score,
            ml_score=ml_score,
            final_risk_score=compute_final_risk_score(rule_score, ml_score),
            risk_level=risk_level,
            model_version=model_version,
            config_version=config_version,
            rule_details=rule_details,
            ml_details=ml_details,
            explanation=explanation,
            features_snapshot=features_snapshot,
            allowed_actions=allowed_actions,
        )
        if assessed_at is not None:
            assessment.assessed_at = assessed_at
        self.add(assessment, {"uq_risk_assessments_transaction_id": AssessmentAlreadyExistsError})
        return assessment

    def get_by_transaction(self, transaction_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> RiskAssessment | None:
        """Pass ``user_id`` for user-facing reads: the transaction must belong to that user."""
        query = select(RiskAssessment).where(RiskAssessment.transaction_id == transaction_id)
        if user_id is not None:
            query = query.join(Transaction, Transaction.id == RiskAssessment.transaction_id).where(
                Transaction.user_id == user_id
            )
        return self.session.scalar(query)

    def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        risk_level: RiskLevel | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[RiskAssessment]:
        query = (
            select(RiskAssessment)
            .join(Transaction, Transaction.id == RiskAssessment.transaction_id)
            .where(Transaction.user_id == user_id)
        )
        if risk_level is not None:
            query = query.where(RiskAssessment.risk_level == risk_level)
        query = (
            query.order_by(RiskAssessment.assessed_at.desc(), RiskAssessment.id)
            .limit(clamp_limit(limit))
            .offset(clamp_offset(offset))
        )
        return list(self.session.scalars(query))
