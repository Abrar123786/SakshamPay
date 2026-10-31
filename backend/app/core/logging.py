"""Structured logging.

Every log line is a single JSON object (or a readable line when LOG_FORMAT=console)
and automatically carries the current request ID, so a user-facing error can be
traced to the exact request. Never log passwords, tokens or request bodies.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else was passed via ``extra=`` and is emitted as a field.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "request_id",
    "color_message",  # uvicorn's ANSI-coloured duplicate of the message
}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if getattr(record, "request_id", None):
            payload["request_id"] = record.request_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS and not k.startswith("_")
        }
        rid = getattr(record, "request_id", None)
        suffix = " ".join(f"{k}={v}" for k, v in extras.items())
        return " ".join(part for part in (base, f"[{rid}]" if rid else "", suffix) if part)


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(ConsoleFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))

    # Replace only the handler this function installed before (create_app may run more
    # than once, e.g. in tests); handlers added by other tools are left in place.
    handler._sakshampay = True  # type: ignore[attr-defined]
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "_sakshampay", False)]
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL)

    # Route uvicorn's own loggers through the same handler. The access logger is
    # silenced because RequestContextMiddleware writes one structured line per request.
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True

    # SQLAlchemy logs every statement whenever its logger is enabled for INFO, so
    # with LOG_LEVEL=DEBUG it would dump SQL and parameters. Only DB_ECHO turns that on.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if settings.DB_ECHO else logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
