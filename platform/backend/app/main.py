"""FastAPI application assembly: middleware, routers, lifespan and the single-page app fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError

from app.api.middleware import RequestBodyLimit, same_origin_cookie_writes
from app.api.routes import ROUTE_MODULES
from app.core import config, database
from app.core.database import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(title="CU AutoReview local API", version="1.0.0", lifespan=lifespan)
# Registration order matters: the body cap wraps the origin check, as before the split.
app.middleware("http")(same_origin_cookie_writes)
app.add_middleware(RequestBodyLimit)
for module in ROUTE_MODULES:
    app.include_router(module.router)


logger = logging.getLogger("cuautoreview.queue")


def startup():
    init_db(database.engine)
    if config.settings.object_store_backend == "s3":
        try:
            import boto3

            client = boto3.client(
                "s3", endpoint_url=config.settings.s3_endpoint_url, region_name=config.settings.aws_region
            )
            buckets = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
            if config.settings.s3_bucket not in buckets:
                client.create_bucket(Bucket=config.settings.s3_bucket)
        except Exception:
            # A transient object-store startup failure should not prevent login/API use.
            app.state.object_store_startup_error = "Object store initialization failed"
    app.state.outbox_relay_task = asyncio.create_task(_outbox_background_loop())


async def _outbox_background_loop():
    """The API owns outbox timing; the Celery worker runs without Beat."""
    from app.worker.queue import recover_expired_leases, relay_outbox

    while True:
        try:
            await asyncio.to_thread(relay_outbox.run)
            await asyncio.to_thread(recover_expired_leases.run)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Avoid logging broker URLs, exception text, or environment data.
            logger.warning("Outbox poll failed (%s)", type(exc).__name__)
        await asyncio.sleep(1)


async def shutdown():
    task = getattr(app.state, "outbox_relay_task", None)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@app.exception_handler(IntegrityError)
def integrity_error_handler(_request: Request, _exc: IntegrityError):
    return Response(
        status_code=409,
        content=json.dumps({"detail": "A conflicting record already exists"}),
        media_type="application/json",
    )


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    dist = (config.PROJECT_ROOT / "platform" / "web" / "dist").resolve()
    if full_path:
        candidate = (dist / full_path).resolve()
        # Resolve symlinks before checking containment so a built asset cannot escape dist.
        if candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        # A missing asset request should remain a 404 rather than returning index.html
        # with the wrong content type and confusing the browser's module loader.
        if Path(full_path).suffix:
            raise HTTPException(404, "Not found")
    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404, "Frontend assets are not built; run the platform web build")
