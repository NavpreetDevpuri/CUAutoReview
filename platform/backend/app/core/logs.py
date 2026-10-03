"""Process-wide logging as text or JSON lines, tagged with the current request id.

Log records carry only what callers pass explicitly: never cookies, passwords, tokens or request bodies.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


class RequestIdFilter(logging.Filter):
    """Attach the request id of the current context (or '-') to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line; structured fields come from the record's ``http`` extra."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "-")
        if request_id != "-":
            payload["request_id"] = request_id
        http = getattr(record, "http", None)
        if isinstance(http, dict):
            payload["http"] = http
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Route the root, uvicorn and Celery loggers through one handler with the chosen format."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(TEXT_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "celery", "celery.task"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    # The API writes its own access line (app.api.middleware.RequestContext) with the request id and user.
    logging.getLogger("uvicorn.access").disabled = True
