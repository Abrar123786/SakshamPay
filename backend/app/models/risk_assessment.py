import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.database.base import Base
from app.models.common import UUIDPrimaryKeyMixin, assert_no_sensitive_keys, enum_column, make_append_only
from app.models.enums import RiskLevel

if TYPE_CHECKING:
    from app.models.alert import Alert
    from app.models.transaction import Transaction

# Approved P-1 formula: final = 0.6 x rule + 0.4 x ml. Written as (3R + 2M) / 5 so the
# database computes it exactly; the result is never exactly .5, so rounding is unambiguous.
FINAL_SCORE_FORMULA_SQL = (
    "(ml_score IS NULL AND final_risk_score = rule_score)"
    " OR (ml_score IS NOT NULL"
    " AND final_risk_score = round((3 * rule_score + 2 * ml_score)::numeric / 5))"
)


def compute_final_risk_score(rule_score: int, ml_score: int | None) -> int:
    """Python twin of the database check, for services and tests.

    Uses integer arithmetic so it agrees with PostgreSQL's round() exactly.
    """
    if ml_score is None:
        return rule_score
    numerator = 3 * rule_score + 2 * ml_score  # 5 x (0.6R + 0.4M)
    return (numerator + 2) // 5  # remainder 0-4 out of 5; never a .5 tie


class RiskAssessment(UUIDPrimaryKeyMixin, Base):
    """The immutable result of assessing one transaction (at most one per transaction).

    Scores are integers 0-100. ``ml_score`` is NULL when the anomaly model was
    unavailable (P-1 rules-only fallback), in which case the final score equals
    the rule score. Rows are append-only.
    """

    __tablename__ = "risk_assessments"
    __table_args__ = (
        UniqueConstraint("transaction_id"),
        UniqueConstraint("id", "transaction_id"),  # target of the consistency FK from alerts
        CheckConstraint("rule_score BETWEEN 0 AND 100", name="rule_score_range"),
        CheckConstraint("ml_score BETWEEN 0 AND 100", name="ml_score_range"),
        CheckConstraint("final_risk_score BETWEEN 0 AND 100", name="final_risk_score_range"),
        CheckConstraint(FINAL_SCORE_FORMULA_SQL, name="final_score_formula"),
        CheckConstraint("(ml_score IS NULL) = (model_version IS NULL)", name="model_version_matches_ml"),
        CheckConstraint("(ml_score IS NULL) = (ml_details IS NULL)", name="ml_details_matches_ml"),
        CheckConstraint("jsonb_typeof(rule_details) = 'array'", name="rule_details_array"),
        CheckConstraint("jsonb_typeof(ml_details) = 'object'", name="ml_details_object"),
        CheckConstraint("jsonb_typeof(explanation) = 'array'", name="explanation_array"),
        CheckConstraint("jsonb_typeof(features_snapshot) = 'object'", name="features_snapshot_object"),
        CheckConstraint(
            "jsonb_typeof(allowed_actions) = 'array' AND jsonb_array_length(allowed_actions) > 0",
            name="allowed_actions_non_empty",
        ),
        Index("ix_risk_assessments_risk_level_assessed_at", "risk_level", "assessed_at"),
    )

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="RESTRICT")
    )
    rule_score: Mapped[int] = mapped_column(SmallInteger)
    ml_score: Mapped[int | None] = mapped_column(SmallInteger)
    final_risk_score: Mapped[int] = mapped_column(SmallInteger)
    risk_level: Mapped[RiskLevel] = mapped_column(enum_column(RiskLevel, "risk_level", 8))
    model_version: Mapped[str | None] = mapped_column(String(64))
    config_version: Mapped[str] = mapped_column(String(64))
    rule_details: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # none_as_null: Python None must become SQL NULL, not the JSON value null,
    # or the "(ml_score IS NULL) = (ml_details IS NULL)" check fails for rules-only rows.
    ml_details: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    explanation: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    features_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    allowed_actions: Mapped[list[str]] = mapped_column(JSONB)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transaction: Mapped["Transaction"] = relationship(back_populates="risk_assessment")
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="risk_assessment",
        primaryjoin="RiskAssessment.id == foreign(Alert.risk_assessment_id)",
    )

    @validates("rule_details", "ml_details", "explanation", "features_snapshot")
    def _no_sensitive_keys(self, key: str, value: Any) -> Any:
        return assert_no_sensitive_keys(value, key)

    def __repr__(self) -> str:
        return f"<RiskAssessment id={self.id} final={self.final_risk_score} level={self.risk_level}>"


make_append_only(RiskAssessment)
