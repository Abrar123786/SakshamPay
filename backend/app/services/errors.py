"""Errors raised by the payment services (P-10). All are ``AppError`` subclasses,
so an endpoint that lets one escape answers with the standard error shape."""

from app.core.exceptions import AppError, ConflictError


class AmountOutOfRangeError(AppError):
    status_code = 422
    code = "AMOUNT_OUT_OF_RANGE"
    message = "The amount is outside the limits for a simulated payment."


class ConfirmationRequiredError(AppError):
    status_code = 400
    code = "CONFIRMATION_REQUIRED"
    message = "Confirm that you have read the warning before continuing."


class StepUpRequiredError(AppError):
    status_code = 403
    code = "STEP_UP_REQUIRED"
    message = "This payment needs verification before it can continue."


class VerificationFailedError(AppError):
    status_code = 403
    code = "VERIFICATION_FAILED"
    message = "The password was not correct."


class TooManyVerificationAttemptsError(AppError):
    status_code = 429
    code = "TOO_MANY_VERIFICATION_ATTEMPTS"
    message = "Too many failed verification attempts. Try again later."


class ActionNotAllowedError(ConflictError):
    code = "ACTION_NOT_ALLOWED"
    message = "This action is not available for this payment."


class TransactionExpiredError(ConflictError):
    code = "TRANSACTION_EXPIRED"
    message = "The time to decide on this payment has passed, so it was not sent. Nothing was paid."
