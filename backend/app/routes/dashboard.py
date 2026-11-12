"""Dashboard endpoint: GET /api/v1/dashboard/summary (P-9)."""

from fastapi import APIRouter, Response

from app.database.session import ReadOnlyDbSession
from app.routes.dependencies import CurrentUser
from app.schemas.dashboard import DashboardSummary
from app.schemas.errors import ErrorResponse
from app.services.dashboard import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Your last 30 days at a glance",
    description=(
        "Counts and totals for the signed-in user's transactions created in the last 30 days, "
        "plus the number of unread alerts. Read-only; the user is taken from the access token."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "NOT_AUTHENTICATED, INVALID_TOKEN or TOKEN_EXPIRED"},
        503: {"model": ErrorResponse, "description": "Database or authentication not available"},
    },
)
def dashboard_summary(user: CurrentUser, session: ReadOnlyDbSession, response: Response) -> DashboardSummary:
    # CurrentUser is resolved first, on the request's normal session (unchanged P-6
    # behaviour). The aggregates run on a separate session whose transaction is
    # read-only from its first statement (get_read_only_db).
    # Personal financial data: never stored by browsers or proxies. Set here explicitly
    # rather than relying only on the global default in RequestContextMiddleware.
    response.headers["Cache-Control"] = "no-store"
    return DashboardService(session).summary(user.id)
