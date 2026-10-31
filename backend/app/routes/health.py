"""Liveness endpoint.

Served at ``GET /health`` (for Render's health check and uptime monitors) and at
``GET /api/v1/health`` (so the frontend can reach it through its versioned base URL).
It deliberately does not touch the database: liveness must not fail because a
dependency is down. A separate readiness check (database + model) arrives with
those components.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.schemas.health import HealthResponse

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(status="healthy", application=settings.APP_NAME, version=settings.APP_VERSION)
