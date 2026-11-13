"""Request and response models for /api/v1/transactions (P-10).

Requests forbid unknown fields, so a client cannot send a status, score, level
or allowed actions (P-1). Responses are built from stored rows only. They never
include the feature snapshot, the rule observations or trigger values, and never
a full payment identifier.
"""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, field_validator, model_validator

from app.fraud_detection.config import RiskConfig
from app.models import ApprovalMethod, Beneficiary, RiskAssessment, RiskLevel, Transaction, TransactionStatus, TransactionType
from app.models.transaction import MAX_VERIFY_ATTEMPTS
from app.schemas.common import UtcDateTime

MIN_AMOUNT_PAISE = 100  # Rs 1
DESCRIPTION_MAX_LENGTH = 80


class TransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beneficiary_id: uuid.UUID
    # Integer paise only (no floats, no strings). The upper limit is a setting, checked by the service.
    amount_paise: StrictInt = Field(ge=MIN_AMOUNT_PAISE)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    transaction_type: TransactionType = TransactionType.P2P

    @field_validator("description")
    @classmethod
    def _plain_note(cls, value):
        if value is None:
            return None
        value = value.strip()
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("Use plain text without control characters.")
        return value or None

    def request_hash(self) -> str:
        """SHA-256 of the canonical request, stored to detect an Idempotency-Key reused for a different payment."""
        canonical = json.dumps(
            {
                "amount_paise": self.amount_paise,
                "beneficiary_id": str(self.beneficiary_id),
                "description": self.description,
                "transaction_type": self.transaction_type.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


class ActionRequest(BaseModel):
    """CANCEL; CONTINUE (with ``confirmed: true`` when the level is MEDIUM); VERIFY (with the account password)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["CANCEL", "CONTINUE", "VERIFY"]
    confirmed: StrictBool | None = None
    password: SecretStr | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _fields_match_action(self):
        if self.action == "VERIFY":
            if self.password is None or not self.password.get_secret_value():
                raise ValueError("VERIFY needs your password.")
        elif self.password is not None:
            raise ValueError("A password is only used with VERIFY.")
        if self.confirmed is not None and self.action != "CONTINUE":
            raise ValueError("`confirmed` is only used with CONTINUE.")
        return self


class BeneficiarySummary(BaseModel):
    id: uuid.UUID
    beneficiary_name: str
    bank_name: str | None
    upi_id_masked: str | None
    account_reference_masked: str | None


class RiskFactor(BaseModel):
    code: str
    source: Literal["rule", "ml", "system"]
    label: str
    detail: str | None = None
    points: int | None = None


class RiskBands(BaseModel):
    low_max: int
    medium_max: int


class AssessmentOut(BaseModel):
    final_risk_score: int = Field(description="0-100 relative risk indicator. Not a probability of fraud.")
    risk_level: RiskLevel
    rule_score: int
    ml_score: int | None = Field(description="Null while no behaviour model is available.")
    ml_available: bool
    level_raised_from: RiskLevel | None = Field(
        description="Set when the level was raised from the band the score falls in (rules-only assessments raise LOW to MEDIUM)."
    )
    bands: RiskBands
    factors: list[RiskFactor]
    allowed_actions: list[str]
    recommended_action: str
    requires_confirmation: bool
    assessed_at: UtcDateTime


class TransactionOut(BaseModel):
    id: uuid.UUID
    status: TransactionStatus
    amount_paise: int
    currency: str
    transaction_type: TransactionType
    description: str | None
    beneficiary: BeneficiarySummary
    initiated_at: UtcDateTime
    expires_at: UtcDateTime | None
    completed_at: UtcDateTime | None
    approval_method: ApprovalMethod | None
    verify_attempts_remaining: int
    server_time: UtcDateTime
    assessment: AssessmentOut | None = Field(description="Null until assessed, and for FAILED payments.")


def _summary(assessment: RiskAssessment) -> dict[str, Any]:
    for entry in reversed(assessment.rule_details or []):
        if isinstance(entry, dict) and entry.get("summary") is True:
            return entry
    return {}


def assessment_view(assessment: RiskAssessment, config: RiskConfig) -> AssessmentOut:
    """What the user may see of a stored assessment. Values recorded at assessment time
    win; the current configuration only fills gaps for rows without them (seed data)."""
    summary = _summary(assessment)
    band = RiskLevel(summary["band_level"]) if summary.get("band_level") else config.band(assessment.final_risk_score)
    return AssessmentOut(
        final_risk_score=assessment.final_risk_score,
        risk_level=assessment.risk_level,
        rule_score=assessment.rule_score,
        ml_score=assessment.ml_score,
        ml_available=assessment.ml_score is not None,
        level_raised_from=band if band != assessment.risk_level else None,
        bands=RiskBands(**(summary.get("bands") or {"low_max": config.low_max, "medium_max": config.medium_max})),
        factors=[
            RiskFactor(**{key: item.get(key) for key in ("code", "source", "label", "detail", "points")})
            for item in assessment.explanation
        ],
        allowed_actions=list(assessment.allowed_actions),
        recommended_action=summary.get("recommended_action") or config.recommended_action[assessment.risk_level],
        requires_confirmation=summary.get("requires_confirmation", assessment.risk_level == RiskLevel.MEDIUM),
        assessed_at=assessment.assessed_at,
    )


def transaction_view(
    transaction: Transaction,
    beneficiary: Beneficiary,
    assessment: RiskAssessment | None,
    *,
    now: datetime,
    config: RiskConfig,
) -> TransactionOut:
    return TransactionOut(
        id=transaction.id,
        status=transaction.status,
        amount_paise=transaction.amount_paise,
        currency=transaction.currency,
        transaction_type=transaction.transaction_type,
        description=transaction.description,
        beneficiary=BeneficiarySummary(
            id=beneficiary.id,
            beneficiary_name=beneficiary.beneficiary_name,
            bank_name=beneficiary.bank_name,
            upi_id_masked=beneficiary.upi_id_masked,
            account_reference_masked=beneficiary.account_reference_masked,
        ),
        initiated_at=transaction.initiated_at,
        expires_at=transaction.expires_at,
        completed_at=transaction.completed_at,
        approval_method=transaction.approval_method,
        verify_attempts_remaining=MAX_VERIFY_ATTEMPTS - transaction.verify_attempts,
        server_time=now,
        assessment=assessment_view(assessment, config) if assessment is not None else None,
    )
