"""Unversioned system endpoints: service info, liveness and readiness.

These sit outside ``/api/v1`` on purpose: hosting platforms and uptime monitors
call them, and they must not change when the business API gets a new version.

* ``GET /``             service info and entry points
* ``GET /health``       liveness: never touches the database, so a database
                        outage cannot make the platform restart a healthy process
* ``GET /health/ready`` readiness: checks the database when it is configured;
                        503 when a configured database cannot be reached
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.core.config import Settings
from app.database.session import Database, get_database
from app.schemas.system import (
    DatabaseCheck,
    HealthResponse,
    ReadinessChecks,
    ReadinessResponse,
    ServiceInfo,
)

router = APIRouter(tags=["System"])


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


AppSettings = Annotated[Settings, Depends(get_app_settings)]


@router.get("/", response_model=ServiceInfo, summary="Service information")
def service_info(settings: AppSettings) -> ServiceInfo:
    return ServiceInfo(
        application=settings.APP_NAME,
        version=settings.APP_VERSION,
        api_base=settings.API_V1_PREFIX,
        health="/health",
        readiness="/health/ready",
        docs="/docs" if settings.docs_enabled else None,
    )


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(settings: AppSettings) -> HealthResponse:
    return HealthResponse(status="healthy", application=settings.APP_NAME, version=settings.APP_VERSION)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    responses={503: {"model": ReadinessResponse, "description": "A configured dependency is unavailable"}},
)
async def readiness(
    settings: AppSettings,
    database: Annotated[Database, Depends(get_database)],
) -> JSONResponse:
    # check_connection() is blocking I/O: keep it off the event loop.
    db_status = await run_in_threadpool(database.check_connection)
    ready = db_status.state != "unavailable"
    body = ReadinessResponse(
        status="ready" if ready else "not_ready",
        application=settings.APP_NAME,
        version=settings.APP_VERSION,
        checks=ReadinessChecks(database=DatabaseCheck(status=db_status.state, latency_ms=db_status.latency_ms)),
    )
    return JSONResponse(status_code=200 if ready else 503, content=body.model_dump())
