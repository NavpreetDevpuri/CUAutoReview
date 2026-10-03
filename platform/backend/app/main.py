"""FastAPI application assembly: middleware, routers, lifespan and the single-page app fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError

from app.api.middleware import RequestBodyLimit, RequestContext, SecurityHeaders, same_origin_cookie_writes
from app.api.routes import ROUTE_MODULES
from app.core import config, database, migrate
from app.core.logs import configure_logging
from app.services.maintenance import prune_expired

# How often the background loop removes expired sessions and stale login attempts.
MAINTENANCE_INTERVAL_SECONDS = 300


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    try:
        yield
    finally:
        await shutdown()


_docs = config.settings.expose_api_docs
app = FastAPI(
    title="CU AutoReview local API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs else None,
    redoc_url="/redoc" if _docs else None,
    openapi_url="/openapi.json" if _docs else None,
)
# Each registration wraps the previous one, so the outermost layer is added last:
# request id + access log -> security headers -> body cap -> same-origin writes -> routes.
app.middleware("http")(same_origin_cookie_writes)
app.add_middleware(RequestBodyLimit)
app.add_middleware(SecurityHeaders)
app.add_middleware(RequestContext)
for module in ROUTE_MODULES:
    app.include_router(module.router)


logger = logging.getLogger("cuautoreview.app")


def startup():
    config.check_settings()
    configure_logging(config.settings.log_level, config.settings.log_format)
    try:
        if config.settings.auto_migrate:
            logger.info("%s", migrate.upgrade(database.engine))
        else:
            # Production applies migrations in a separate one-shot job, never from serving replicas.
            migrate.require_head(database.engine)
    except migrate.SchemaError as exc:
        logger.error("%s", exc)
        raise
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


def run_maintenance() -> None:
    with database.SessionLocal() as db:
        removed = prune_expired(db)
        db.commit()
    if any(removed.values()):
        logger.info("Removed %(sessions)s expired sessions and %(login_attempts)s stale login attempts", removed)


async def _outbox_background_loop():
    """The API owns outbox timing and housekeeping; the Celery worker runs without Beat."""
    from app.worker.queue import recover_expired_leases, relay_outbox

    next_maintenance = time.monotonic()
    while True:
        try:
            await asyncio.to_thread(relay_outbox.run)
            await asyncio.to_thread(recover_expired_leases.run)
            if time.monotonic() >= next_maintenance:
                next_maintenance = time.monotonic() + MAINTENANCE_INTERVAL_SECONDS
                await asyncio.to_thread(run_maintenance)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Avoid logging broker URLs, exception text, or environment data.
            logger.warning("Background poll failed (%s)", type(exc).__name__)
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
