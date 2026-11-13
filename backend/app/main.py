"""SakshamPay API entry point and application factory.

Run locally (from backend/):  uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import MIN_JWT_SECRET_LENGTH, Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.database.session import Database
from app.fraud_detection.ml import UnavailableScorer
from app.middleware.request_context import RequestContextMiddleware
from app.routes import api_router, system

logger = logging.getLogger("sakshampay")

CORS_ALLOWED_METHODS = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
CORS_ALLOWED_HEADERS = ["Authorization", "Content-Type", "Idempotency-Key", "X-Device-Id", "X-Request-ID"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    database: Database = app.state.database

    logger.info("Starting application", extra=settings.safe_summary())

    # Connectivity is checked only when a database is configured, and a failure is
    # logged rather than fatal: /health keeps answering and /health/ready reports 503
    # until the database becomes reachable.
    if database.is_configured:
        status = await run_in_threadpool(database.check_connection)
        if status.state == "ok":
            logger.info("Database reachable", extra={"latency_ms": status.latency_ms})
        else:
            logger.error(
                "Database configured but unreachable; continuing without it",
                extra={"error_type": status.error_type},
            )
    else:
        logger.warning("DATABASE_URL is not set; running without a database (development only)")

    if settings.JWT_SECRET_KEY is None or len(settings.JWT_SECRET_KEY.get_secret_value()) < MIN_JWT_SECRET_LENGTH:
        logger.warning("JWT_SECRET_KEY is missing or too short; login and protected endpoints will return 503")

    if settings.IDENTIFIER_HASH_KEY is None:
        logger.warning("IDENTIFIER_HASH_KEY is not set; adding beneficiaries and making payments will fail")

    if settings.VERIFY_PREFIX_LIMIT_ENABLED:
        # Only meaningful when the app sees real client addresses (FORWARDED_ALLOW_IPS behind a proxy).
        logger.info("Per-network Verify limit is on", extra={"limit": settings.VERIFY_PREFIX_FAILURE_LIMIT})
    if settings.LOGIN_PREFIX_LIMIT_ENABLED:
        logger.info("Per-network login limit is on", extra={"limit": settings.LOGIN_PREFIX_FAILURE_LIMIT})

    yield

    logger.info("Shutting down application")
    database.dispose()
    logger.info("Application stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        version=settings.APP_VERSION,
        description=(
            "Pre-transaction risk assessment for simulated digital payments. Prototype only: "
            "not connected to UPI, NPCI or any bank.\n\n"
            f"Versioned business endpoints live under `{settings.API_V1_PREFIX}`. "
            "System endpoints (`/`, `/health`, `/health/ready`) are unversioned."
        ),
        debug=settings.DEBUG,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.database = Database(settings)
    # No anomaly model exists yet: every assessment runs in P-1's rules-only mode.
    app.state.anomaly_scorer = UnavailableScorer()

    # Middleware order: the last one added is the outermost. CORS wraps
    # RequestContextMiddleware so that error responses also carry CORS headers.
    app.add_middleware(RequestContextMiddleware, max_body_bytes=settings.MAX_REQUEST_BODY_BYTES)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies (P-1 decision D12)
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    register_exception_handlers(app)

    app.include_router(system.router)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
