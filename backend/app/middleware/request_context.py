"""Request context middleware (pure ASGI).

For every HTTP request it:
  * accepts a well-formed incoming ``X-Request-ID`` or generates one,
  * exposes it to logs (context variable) and returns it as a response header,
  * adds baseline security headers to every response,
  * writes one structured access-log line with status and duration,
  * converts unexpected exceptions into the standard JSON 500 response.

It is registered *inside* CORSMiddleware, so even error responses carry CORS
headers and the browser can read them.
"""

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import internal_error_response
from app.core.logging import request_id_var

logger = logging.getLogger("sakshampay.access")
error_logger = logging.getLogger("sakshampay.errors")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cache-control", b"no-store"),
)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)

        started = time.perf_counter()
        status_code = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = list(message.get("headers", []))
                existing = {name.lower() for name, _ in headers}
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                headers.extend(h for h in SECURITY_HEADERS if h[0] not in existing)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            error_logger.exception("Unhandled exception", extra={"path": scope.get("path")})
            if response_started:
                raise
            await internal_error_response()(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
