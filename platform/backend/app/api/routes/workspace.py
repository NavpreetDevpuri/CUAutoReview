"""Workspace overview and activity feed."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_user
from app.core import config
from app.core.database import get_db
from app.models import ActivityEvent, Batch, BatchMember, Dataset, Job, User
from app.services.access import visible_batch_ids
from app.services.records import record
from app.services.views import batch_detail

router = APIRouter()


@router.get("/api/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(get_user)):
    workspace_wide = user.role in ("admin", "manager")
    batch_ids = visible_batch_ids(db, user)
    if workspace_wide:
        batch_count = db.scalar(select(func.count(Batch.id)).where(Batch.workspace_id == user.workspace_id)) or 0
        dataset_count = db.scalar(select(func.count(Dataset.id)).where(Dataset.workspace_id == user.workspace_id)) or 0
        task_count = (
            db.scalar(
                select(func.count(BatchMember.id))
                .join(Batch, BatchMember.batch_id == Batch.id)
                .where(Batch.workspace_id == user.workspace_id)
            )
            or 0
        )
    elif batch_ids:
        batch_count = len(batch_ids)
        dataset_count = db.scalar(select(func.count(distinct(Batch.dataset_id))).where(Batch.id.in_(batch_ids))) or 0
        task_count = db.scalar(select(func.count(BatchMember.id)).where(BatchMember.batch_id.in_(batch_ids))) or 0
    else:
        batch_count = dataset_count = task_count = 0
    job_counts = {
        status: (
            db.scalar(
                select(func.count(Job.id)).where(
                    Job.workspace_id == user.workspace_id,
                    Job.status == status,
                    *([] if workspace_wide else [Job.batch_id.in_(batch_ids)]),
                )
            )
            or 0
        )
        if (workspace_wide or batch_ids)
        else 0
        for status in ("queued", "running", "failed", "completed")
    }
    recent_query = select(Batch).where(Batch.workspace_id == user.workspace_id)
    if not workspace_wide:
        recent_query = recent_query.where(Batch.id.in_(batch_ids)) if batch_ids else recent_query.where(False)
    recent = db.scalars(recent_query.order_by(Batch.created_at.desc()).limit(5)).all()
    event_query = select(ActivityEvent).where(ActivityEvent.workspace_id == user.workspace_id)
    if not workspace_wide:
        event_query = event_query.where(ActivityEvent.actor_id == user.id)
    events = db.scalars(event_query.order_by(ActivityEvent.created_at.desc()).limit(12)).all()
    counts = {"datasets": dataset_count, "batches": batch_count, "tasks": task_count, "jobs": sum(job_counts.values())}
    return {
        "counts": counts,
        "datasets": dataset_count,
        "batches": batch_count,
        "jobs": job_counts,
        "tasks": task_count,
        "recent_batches": [batch_detail(db, b) for b in recent],
        "activity": [record(e) for e in events],
        "provider_mode": "explicit opt-in only",
        "queue_mode": "Celery + SQL outbox",
        "storage_mode": config.settings.object_store_backend,
        "seed_replay": any(b.name == "Retained POC replay" for b in recent),
    }


@router.get("/api/activity")
def activity_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    query = select(ActivityEvent).where(ActivityEvent.workspace_id == user.workspace_id)
    if user.role not in ("admin", "manager"):
        query = query.where(ActivityEvent.actor_id == user.id)
    query = query.order_by(ActivityEvent.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    size = min(per_page, 500)
    items = db.scalars(query.offset((page - 1) * size).limit(size)).all()
    return {"items": [record(item) for item in items], "total": total}
