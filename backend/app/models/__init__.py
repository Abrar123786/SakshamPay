"""SQLAlchemy ORM models for the six core tables.

Importing this package registers every model on ``Base.metadata`` (Alembic's
``migrations/env.py`` relies on that). Modules reference each other only by
class name in ``relationship()`` strings, so there are no circular imports.
Schema reference: ``docs/database-schema.md``.
"""

from app.database.base import Base
from app.models.alert import Alert
from app.models.audit_log import AuditLog
from app.models.beneficiary import Beneficiary
from app.models.common import ImmutableRecordError
from app.models.enums import (
    AlertSeverity,
    AlertType,
    ApprovalMethod,
    AuditActorType,
    RiskLevel,
    TransactionStatus,
    TransactionType,
)
from app.models.risk_assessment import RiskAssessment, compute_final_risk_score
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "Alert",
    "AlertSeverity",
    "AlertType",
    "ApprovalMethod",
    "AuditActorType",
    "AuditLog",
    "Base",
    "Beneficiary",
    "ImmutableRecordError",
    "RiskAssessment",
    "RiskLevel",
    "Transaction",
    "TransactionStatus",
    "TransactionType",
    "User",
    "compute_final_risk_score",
]
