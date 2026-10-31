"""SakshamPay API entry point.

Run locally:  uvicorn app.main:app --reload --port 8000   (from the backend/ directory)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.middleware.request_context import RequestContextMiddleware
from app.routes import api_router, health

logger = logging.getLogger("sakshampay")

CORS_ALLOWED_HEADERS = ["Authorization", "Content-Type", "Idempotency-Key", "X-Device-Id", "X-Request-ID"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info(
            "Starting application",
            extra={
                "app_env": settings.APP_ENV,
                "version": settings.APP_VERSION,
                "cors_origins": settings.cors_origins,
                "database_configured": settings.DATABASE_URL is not None,
            },
        )
        yield
        logger.info("Application stopped")

    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        version=settings.APP_VERSION,
        description="Pre-transaction risk assessment for simulated digital payments. Prototype only.",
        debug=settings.DEBUG,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # Middleware order: the last one added is the outermost. CORS must wrap
    # RequestContextMiddleware so that error responses also get CORS headers.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies (P-1 decision D12)
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=["X-Request-ID"],
        max_age=600,
    )

    register_exception_handlers(app)

    app.include_router(health.router)  # GET /health (platform health checks)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)  # GET /api/v1/health, ...

    return app


app = create_app()
