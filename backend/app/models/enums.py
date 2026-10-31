"""Enumerations shared by models (and, later, schemas and services).

Stored as VARCHAR with a named CHECK constraint rather than a native PostgreSQL
ENUM type: adding a value later is a plain constraint change in a migration.
"""

from enum import StrEnum


class TransactionStatus(StrEnum):
    """P-1 transaction lifecycle."""

    INITIATED = "INITIATED"
    ANALYSED = "ANALYSED"
    AWAITING_USER_ACTION = "AWAITING_USER_ACTION"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


TERMINAL_TRANSACTION_STATUSES = frozenset(
    {
        TransactionStatus.APPROVED,
        TransactionStatus.CANCELLED,
        TransactionStatus.EXPIRED,
        TransactionStatus.FAILED,
    }
)


class TransactionType(StrEnum):
    P2P = "P2P"  # person to person
    P2M = "P2M"  # person to merchant


class ApprovalMethod(StrEnum):
    CONTINUE = "CONTINUE"  # user continued after seeing a LOW/MEDIUM assessment
    VERIFIED = "VERIFIED"  # user passed step-up verification


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertType(StrEnum):
    RISK_WARNING = "RISK_WARNING"
    TRANSACTION_APPROVED = "TRANSACTION_APPROVED"
    TRANSACTION_CANCELLED = "TRANSACTION_CANCELLED"
    TRANSACTION_EXPIRED = "TRANSACTION_EXPIRED"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    SECURITY_NOTICE = "SECURITY_NOTICE"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AuditActorType(StrEnum):
    USER = "USER"  # an authenticated user acted
    SYSTEM = "SYSTEM"  # the application acted (expiry sweep, startup checks)
    ANONYMOUS = "ANONYMOUS"  # unauthenticated request, e.g. a failed login
