"""Exception types and handlers.

Every error response, whatever its cause, has one shape:

    {"error": {"code": "...", "message": "...", "request_id": "..."}}

Validation errors add a ``details`` list. Internal details (stack traces, SQL)
are logged, never returned to the client.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

logger = logging.getLogger("sakshampay.errors")

_HTTP_CODE_NAMES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    503: "SERVICE_UNAVAILABLE",
}


class AppError(Exception):
    """Base class for expected, client-facing errors raised by services."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"
    message: str = "The request could not be processed."

    def __init__(self, message: str | None = None, *, code: str | None = None, status_code: int | None = None):
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"
    message = "The request conflicts with the current state of the resource."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
    message = "A required service is temporarily unavailable. Please try again."


def error_body(code: str, message: str, **extra) -> dict:
    body = {"code": code, "message": message, "request_id": request_id_var.get()}
    body.update(extra)
    return {"error": body}


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    log = logger.error if exc.status_code >= 500 else logger.info
    log("Application error", extra={"code": exc.code, "status_code": exc.status_code})
    return JSONResponse(status_code=exc.status_code, content=error_body(exc.code, exc.message))


async def _http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODE_NAMES.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be processed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message),
        headers=getattr(exc, "headers", None),
    )


async def _validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"location": list(err.get("loc", ())), "message": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder(
            error_body("VALIDATION_ERROR", "Some fields are missing or invalid.", details=details)
        ),
    )


def internal_error_response() -> JSONResponse:
    """Response for unexpected exceptions; produced by RequestContextMiddleware so that
    it still passes through CORS (Starlette's default 500 handler sits outside CORS)."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body("INTERNAL_ERROR", "An unexpected error occurred. Please try again."),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
