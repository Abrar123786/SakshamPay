"""Beneficiary endpoints: GET and POST /api/v1/beneficiaries (P-10)."""

from fastapi import APIRouter, Request, status

from app.database.session import DbSession
from app.routes.dependencies import CurrentUser
from app.schemas.beneficiaries import BeneficiaryCreate, BeneficiaryList, BeneficiaryOut
from app.schemas.errors import ErrorResponse
from app.services.auth import ClientInfo
from app.services.beneficiaries import BeneficiaryService

router = APIRouter(prefix="/beneficiaries", tags=["Beneficiaries"])

_UNAUTHENTICATED = {"model": ErrorResponse, "description": "NOT_AUTHENTICATED, INVALID_TOKEN or TOKEN_EXPIRED"}


@router.get(
    "",
    response_model=BeneficiaryList,
    summary="Your saved payees",
    description="The signed-in user's active payees, newest first. Identifiers are masked.",
    responses={401: _UNAUTHENTICATED},
)
def list_beneficiaries(request: Request, user: CurrentUser, session: DbSession) -> BeneficiaryList:
    service = BeneficiaryService(session, request.app.state.settings)
    return BeneficiaryList(items=[BeneficiaryOut.model_validate(item) for item in service.list(user)])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BeneficiaryOut,
    summary="Add a simulated payee",
    description=(
        "Simulated payees only: do not enter real bank or UPI details. Give either `upi_id` or "
        "`account_reference`. The identifier is never stored or returned in full."
    ),
    responses={
        401: _UNAUTHENTICATED,
        409: {"model": ErrorResponse, "description": "BENEFICIARY_ALREADY_EXISTS"},
        422: {"model": ErrorResponse, "description": "VALIDATION_ERROR or INVALID_IDENTIFIER"},
    },
)
def add_beneficiary(body: BeneficiaryCreate, request: Request, user: CurrentUser, session: DbSession) -> BeneficiaryOut:
    service = BeneficiaryService(session, request.app.state.settings)
    beneficiary = service.add(user, body, client=ClientInfo.from_request(request))
    return BeneficiaryOut.model_validate(beneficiary)
