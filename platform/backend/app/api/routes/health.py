"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core import config, database, migrate
from app.core.storage import object_store_reachable

router = APIRouter()


@router.get("/api/health")
def health():
    """Liveness: the process answers. Deliberately checks no dependencies."""
    return {"status": "ok", "queue_mode": "sql_outbox_celery", "object_store": config.settings.object_store_backend}


@router.get("/api/ready")
def ready(response: Response):
    """Readiness: database reachable, schema at this release's head and object store reachable.

    Unauthenticated, so it reports only a status word per component, never error details.
    """
    checks = {"database": "ok", "schema": "ok", "object_store": "ok"}
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = checks["schema"] = "unavailable"
    else:
        try:
            if migrate.current_revision(database.engine) != migrate.head_revision():
                checks["schema"] = "outdated"
        except Exception:
            checks["schema"] = "unavailable"
    if not object_store_reachable(config.settings):
        checks["object_store"] = "unavailable"
    ok = all(value == "ok" for value in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ready" if ok else "not_ready", "checks": checks}
