"""Data-access layer: one repository per table.

Rules:
  * the only layer that builds queries; user data is always filtered by user ID;
  * repositories flush (inside a savepoint) and never commit: the caller owns the
    database transaction (``session.commit()`` / ``session.rollback()``);
  * no delete methods: financial and audit history is never removed;
  * known constraint violations become domain errors (``errors.py``), which are
    ``AppError`` subclasses with HTTP status codes.
"""

from app.repositories.alerts import AlertRepository
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.beneficiaries import BeneficiaryRepository
from app.repositories.risk_assessments import RiskAssessmentRepository
from app.repositories.transactions import ALLOWED_TRANSITIONS, CreateResult, TransactionRepository
from app.repositories.users import UserRepository

__all__ = [
    "ALLOWED_TRANSITIONS",
    "AlertRepository",
    "AuditLogRepository",
    "BeneficiaryRepository",
    "CreateResult",
    "RiskAssessmentRepository",
    "TransactionRepository",
    "UserRepository",
]
