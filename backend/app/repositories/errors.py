"""Errors raised by repositories.

They extend the P-3 ``AppError`` family, so when a later phase lets one escape
from an endpoint it already becomes the right HTTP status and error code.
"""

from app.core.exceptions import ConflictError, NotFoundError


class UserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"
    message = "User not found."


class EmailAlreadyRegisteredError(ConflictError):
    code = "EMAIL_ALREADY_REGISTERED"
    message = "An account with this email already exists."


class PhoneAlreadyRegisteredError(ConflictError):
    code = "PHONE_ALREADY_REGISTERED"
    message = "An account with this phone number already exists."


class BeneficiaryNotFoundError(NotFoundError):
    code = "BENEFICIARY_NOT_FOUND"
    message = "Beneficiary not found."


class DuplicateBeneficiaryError(ConflictError):
    code = "BENEFICIARY_ALREADY_EXISTS"
    message = "This beneficiary is already saved."


class TransactionNotFoundError(NotFoundError):
    code = "TRANSACTION_NOT_FOUND"
    message = "Transaction not found."


class IdempotencyKeyReusedError(ConflictError):
    code = "IDEMPOTENCY_KEY_REUSED"
    message = "This Idempotency-Key was already used for a different request."


class InvalidStateTransitionError(ConflictError):
    code = "INVALID_STATE_TRANSITION"
    message = "The transaction is not in a state that allows this change."


class ConcurrentModificationError(ConflictError):
    code = "CONCURRENT_MODIFICATION"
    message = "The record was changed by another request. Reload and try again."


class AssessmentAlreadyExistsError(ConflictError):
    code = "ASSESSMENT_ALREADY_EXISTS"
    message = "This transaction has already been assessed."


class AlertNotFoundError(NotFoundError):
    code = "ALERT_NOT_FOUND"
    message = "Alert not found."
