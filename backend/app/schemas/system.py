"""Response models for the unversioned system endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ServiceInfo(BaseModel):
    """GET / : what this service is and where its entry points are."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "application": "SakshamPay",
                "version": "1.0.0",
                "api_base": "/api/v1",
                "health": "/health",
                "readiness": "/health/ready",
                "docs": "/docs",
            }
        }
    )

    application: str
    version: str
    api_base: str
    health: str
    readiness: str
    docs: str | None  # null in production, where interactive docs are disabled


class HealthResponse(BaseModel):
    """GET /health : liveness. The process is up and serving requests."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"status": "healthy", "application": "SakshamPay", "version": "1.0.0"}}
    )

    status: Literal["healthy"]
    application: str
    version: str


class DatabaseCheck(BaseModel):
    status: Literal["ok", "not_configured", "unavailable"]
    latency_ms: float | None = None


class ReadinessChecks(BaseModel):
    database: DatabaseCheck


class ReadinessResponse(BaseModel):
    """GET /health/ready : whether the service's dependencies are usable."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ready",
                "application": "SakshamPay",
                "version": "1.0.0",
                "checks": {"database": {"status": "ok", "latency_ms": 2.1}},
            }
        }
    )

    status: Literal["ready", "not_ready"]
    application: str
    version: str
    checks: ReadinessChecks
