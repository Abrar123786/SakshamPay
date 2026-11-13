"""Transaction endpoints (P-10): create and assess, read, and the single action endpoint.

Simulated payments only. Routers hold no business logic: each calls one
``TransactionService`` method. The user always comes from the access token.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response, status

from app.database.session import DbSession
from app.routes.dependencies import CurrentUser
from app.schemas.errors import ErrorResponse
from app.schemas.transactions import ActionRequest, TransactionCreate, TransactionOut
from app.services.auth import ClientInfo
from app.services.transactions import TransactionService

router = APIRouter(prefix="/transactions", tags=["Transactions"])

_TOKEN_PATTERN = r"^[A-Za-z0-9._:-]+$"
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
        pattern=_TOKEN_PATTERN,
        description="One unique value per payment attempt. Send the same value again when retrying that attempt.",
    ),
]
DeviceId = Annotated[
    str,
    Header(
        alias="X-Device-Id",
        min_length=8,
        max_length=128,
        pattern=_TOKEN_PATTERN,
        description="Random identifier the app keeps for this browser. Stored only as a keyed hash.",
    ),
]

_UNAUTHENTICATED = {"model": ErrorResponse, "description": "NOT_AUTHENTICATED, INVALID_TOKEN or TOKEN_EXPIRED"}
_NOT_FOUND = {"model": ErrorResponse, "description": "TRANSACTION_NOT_FOUND (also when it belongs to another user)"}


def _service(request: Request, session) -> TransactionService:
    return TransactionService(session, request.app.state.settings, scorer=request.app.state.anomaly_scorer)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=TransactionOut,
    summary="Start a simulated payment and assess its risk",
    description=(
        "Stores the payment attempt, assesses it and returns the assessment with the actions allowed next. "
        "Nothing is approved here: the payment waits in AWAITING_USER_ACTION for the user's decision. "
        "Repeating a request with the same `Idempotency-Key` returns the stored payment with status 200. "
        "If the assessment cannot complete, the payment is returned as FAILED. No real money moves."
    ),
    responses={
        200: {"model": TransactionOut, "description": "This Idempotency-Key was already used; the stored payment is returned"},
        401: _UNAUTHENTICATED,
        404: {"model": ErrorResponse, "description": "BENEFICIARY_NOT_FOUND (also when inactive or another user's)"},
        409: {"model": ErrorResponse, "description": "IDEMPOTENCY_KEY_REUSED for a different request"},
        422: {"model": ErrorResponse, "description": "VALIDATION_ERROR or AMOUNT_OUT_OF_RANGE"},
    },
)
def create_transaction(
    body: TransactionCreate,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
    device_id: DeviceId,
) -> TransactionOut:
    outcome = _service(request, session).create_and_assess(
        user, body, idempotency_key=idempotency_key, device_id=device_id, client=ClientInfo.from_request(request)
    )
    if not outcome.created:
        response.status_code = status.HTTP_200_OK
    return outcome.transaction


@router.get(
    "/{transaction_id}",
    response_model=TransactionOut,
    summary="One of your payments and its assessment",
    description="Also settles the payment if its decision deadline has passed (it becomes EXPIRED).",
    responses={401: _UNAUTHENTICATED, 404: _NOT_FOUND},
)
def get_transaction(transaction_id: uuid.UUID, request: Request, user: CurrentUser, session: DbSession) -> TransactionOut:
    return _service(request, session).get(user, transaction_id)


@router.post(
    "/{transaction_id}/actions",
    response_model=TransactionOut,
    summary="Cancel, continue or verify a payment that is waiting for your decision",
    description=(
        "The only way a payment's status changes after assessment. CONTINUE is not available for HIGH risk "
        "(use VERIFY); for MEDIUM it needs `confirmed: true`. VERIFY checks your account password; three "
        "failures cancel the payment. Repeating the action that already finished the payment returns it unchanged."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "CONFIRMATION_REQUIRED"},
        401: _UNAUTHENTICATED,
        403: {"model": ErrorResponse, "description": "STEP_UP_REQUIRED or VERIFICATION_FAILED (with context.attempts_remaining)"},
        404: _NOT_FOUND,
        409: {"model": ErrorResponse, "description": "TRANSACTION_EXPIRED, INVALID_STATE_TRANSITION or ACTION_NOT_ALLOWED"},
        422: {"model": ErrorResponse, "description": "VALIDATION_ERROR"},
        429: {"model": ErrorResponse, "description": "TOO_MANY_VERIFICATION_ATTEMPTS"},
    },
)
def apply_action(
    transaction_id: uuid.UUID, body: ActionRequest, request: Request, user: CurrentUser, session: DbSession
) -> TransactionOut:
    return _service(request, session).apply_action(user, transaction_id, body, client=ClientInfo.from_request(request))
