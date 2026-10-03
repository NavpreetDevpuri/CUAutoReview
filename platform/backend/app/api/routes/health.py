"""Service health endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.core import config

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok", "queue_mode": "sql_outbox_celery", "object_store": config.settings.object_store_backend}
