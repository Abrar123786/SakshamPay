"""Authentication endpoints: /api/v1/auth/register, /login and /me."""

from fastapi import APIRouter, Request, status

from app.database.session import DbSession
from app.routes.dependencies import CurrentUser
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserProfile
from app.schemas.errors import ErrorResponse
from app.services.auth import AuthService, ClientInfo

router = APIRouter(prefix="/auth", tags=["Authentication"])

_VALIDATION = {"model": ErrorResponse, "description": "Missing or invalid fields (VALIDATION_ERROR)"}
_UNAVAILABLE = {"model": ErrorResponse, "description": "Database or authentication not available"}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserProfile,
    summary="Create an account",
    responses={
        409: {"model": ErrorResponse, "description": "EMAIL_ALREADY_REGISTERED or PHONE_ALREADY_REGISTERED"},
        422: _VALIDATION,
        503: _UNAVAILABLE,
    },
)
def register(body: RegisterRequest, request: Request, session: DbSession) -> UserProfile:
    service = AuthService(session, request.app.state.settings)
    user = service.register(body, client=ClientInfo.from_request(request))
    return UserProfile.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in and receive an access token",
    responses={
        401: {"model": ErrorResponse, "description": "INVALID_CREDENTIALS (same response for every failure reason)"},
        422: _VALIDATION,
        429: {
            "model": ErrorResponse,
            "description": "TOO_MANY_LOGIN_ATTEMPTS: too many failed logins from this network (only when the per-network limit is on)",
        },
        503: {"model": ErrorResponse, "description": "Database or authentication not available, or SERVICE_BUSY"},
    },
)
def login(body: LoginRequest, request: Request, session: DbSession) -> TokenResponse:
    service = AuthService(session, request.app.state.settings)
    _, token = service.login(body, client=ClientInfo.from_request(request))
    return TokenResponse(access_token=token.token, expires_in=token.expires_in, expires_at=token.expires_at)


@router.get(
    "/me",
    response_model=UserProfile,
    summary="The signed-in user's profile",
    responses={
        401: {"model": ErrorResponse, "description": "NOT_AUTHENTICATED, INVALID_TOKEN or TOKEN_EXPIRED"},
        503: _UNAVAILABLE,
    },
)
def me(user: CurrentUser) -> UserProfile:
    return UserProfile.model_validate(user)
