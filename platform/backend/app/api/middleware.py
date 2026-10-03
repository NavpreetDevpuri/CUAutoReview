"""HTTP middleware: request ids and access logs, security headers, same-origin writes and a body-size cap."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.datastructures import MutableHeaders

from app.core import config
from app.core.config import MAX_IMPORT_BYTES
from app.core.logs import request_id_var

# Global body cap, above the 32 MB import limits so those endpoints keep their specific errors.
MAX_REQUEST_BYTES = MAX_IMPORT_BYTES + 8 * 1024 * 1024

access_logger = logging.getLogger("cuautoreview.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Liveness and readiness probes run every few seconds; log them only at debug level.
_PROBE_PATHS = ("/api/health", "/api/ready")

# The built React/MUI app loads only same-origin scripts; MUI (emotion) injects style elements at runtime.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    )
)
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}
# The interactive API docs load their own assets from a CDN; they are disabled in production.
_DOCS_PATHS = ("/docs", "/docs/oauth2-redirect", "/redoc")


def cache_policy(path: str, status: int) -> str:
    """API responses are never cached; content-hashed build assets are immutable; HTML is revalidated."""
    if path.startswith("/api/"):
        return "no-store"
    if path.startswith("/assets/") and status == 200:
        return "public, max-age=31536000, immutable"
    return "no-cache"


class RequestContext:
    """Assign or propagate X-Request-ID, echo it in the response and write one access-log line per request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        # Shared with request.state, so dependencies can record the signed-in user for the access log.
        state = scope.setdefault("state", {})
        status, started = 500, time.perf_counter()

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["x-request-id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            path = scope.get("path", "")
            client = scope.get("client")
            access_logger.log(
                logging.DEBUG if path in _PROBE_PATHS else logging.INFO,
                "%s %s %s",
                scope.get("method"),
                path,
                status,
                extra={
                    "http": {
                        "method": scope.get("method"),
                        "path": path,
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                        "user_id": state.get("user_id"),
                        "client": client[0] if client else None,
                    }
                },
            )
            request_id_var.reset(token)


class SecurityHeaders:
    """Add browser security headers and a cache policy to every response that does not set its own."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if path not in _DOCS_PATHS:
                    headers.setdefault("content-security-policy", CONTENT_SECURITY_POLICY)
                if config.settings.secure_cookies or config.settings.production:
                    headers.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains")
                headers.setdefault("cache-control", cache_policy(path, message["status"]))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _origin_allowed(request: Request, parsed) -> bool:
    if parsed.path or parsed.query or parsed.fragment:
        return False
    trusted = config.settings.trusted_origins
    if trusted:
        # Behind a TLS-terminating proxy the scheme and Host seen here differ from the browser's origin.
        return f"{parsed.scheme}://{parsed.netloc}".lower() in trusted
    return parsed.scheme == request.url.scheme and parsed.netloc.lower() == request.headers.get("host", "").lower()


async def same_origin_cookie_writes(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                if not _origin_allowed(request, parsed):
                    return Response(
                        status_code=403,
                        content=json.dumps({"detail": "Cross-origin mutation denied"}),
                        media_type="application/json",
                    )
            except ValueError:
                return Response(
                    status_code=403,
                    content=json.dumps({"detail": "Invalid request origin"}),
                    media_type="application/json",
                )
        # Browser fetch sends Origin for unsafe methods. Cookie-authenticated requests without it
        # are rejected unless same-origin Fetch Metadata is explicitly supplied.
        elif (
            request.cookies.get(config.settings.session_cookie)
            and request.headers.get("sec-fetch-site") != "same-origin"
        ):
            return Response(
                status_code=403,
                content=json.dumps({"detail": "Origin required for cookie-authenticated mutation"}),
                media_type="application/json",
            )
    return await call_next(request)


class RequestBodyLimit:
    """Reject oversized bodies before FastAPI buffers them, including unauthenticated requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = MAX_REQUEST_BYTES
        too_large = Response(
            status_code=413, content=json.dumps({"detail": "Request body is too large"}), media_type="application/json"
        )
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            return await too_large(scope, receive, send)
        received, started, rejected = 0, False, False

        async def limited_receive():
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer 413 here; the app then sees a disconnect and its own reply is discarded.
                    rejected = True
                    if not started:
                        await too_large(scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal started
            if rejected:
                return
            started = started or message["type"] == "http.response.start"
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
