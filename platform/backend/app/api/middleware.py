"""HTTP middleware: same-origin checks for cookie-authenticated writes and a global request-body cap."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import Request, Response

from app.core import config
from app.core.config import MAX_IMPORT_BYTES

# Global body cap, above the 32 MB import limits so those endpoints keep their specific errors.
MAX_REQUEST_BYTES = MAX_IMPORT_BYTES + 8 * 1024 * 1024


async def same_origin_cookie_writes(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                host = request.headers.get("host", "")
                if (
                    parsed.scheme != request.url.scheme
                    or parsed.netloc.lower() != host.lower()
                    or parsed.path
                    or parsed.query
                    or parsed.fragment
                ):
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
