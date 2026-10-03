"""Review jobs: listing, detail and manual retry."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_user
from app.core.database import get_db
from app.models import BatchMember, Job, OutboxEvent, PresetRevision, TaskRevision, User, utcnow
from app.schemas import StartBatch
from app.services.access import get_batch, need_batch_manager, visible_batch_ids
from app.services.audit import activity
from app.services.execution import require_preset_budget_confirmation
from app.services.read_cache import preload_attempts, preload_rows
from app.services.records import record
from app.services.runs import lock_batch_status
from app.services.views import job_detail

router = APIRouter()


@router.get("/api/jobs")
def jobs(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    query = select(Job).where(Job.workspace_id == user.workspace_id)
    if user.role not in ("admin", "manager"):
        batch_ids = visible_batch_ids(db, user)
        query = query.where(Job.batch_id.in_(batch_ids)) if batch_ids else query.where(False)
    query = query.order_by(Job.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    size = min(per_page, 500)
    items = db.scalars(query.offset((page - 1) * size).limit(size)).all()
    preload_attempts(db, items)
    preload_rows(db, PresetRevision, {job.preset_revision_id for job in items})
    preload_rows(db, BatchMember, {job.member_id for job in items})
    preload_rows(
        db, TaskRevision, {member.task_revision_id for job in items if (member := db.get(BatchMember, job.member_id))}
    )
    output = []
    for job in items:
        item = job_detail(db, job)
        member = db.get(BatchMember, job.member_id)
        revision = db.get(TaskRevision, member.task_revision_id) if member else None
        item["task_id"] = member.task_id if member else None
        item["task_title"] = revision.content.get("title") if revision else None
        item["outcome"] = (revision.content or {}).get("outcome") if revision else None
        item["score"] = (revision.content or {}).get("score") if revision else None
        item["run_id"] = job.batch_id
        item["attempt"] = job.attempt_count
        output.append(item)
    return {"items": output, "total": total}


@router.get("/api/jobs/{job_id}")
def job_by_id(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    job = db.get(Job, job_id)
    if not job or job.workspace_id != user.workspace_id:
        raise HTTPException(404, "Job not found")
    batch, _role = get_batch(db, job.batch_id, user)
    item = job_detail(db, job)
    member = db.get(BatchMember, job.member_id)
    revision = db.get(TaskRevision, member.task_revision_id) if member else None
    item.update(
        {
            "run_id": batch.id,
            "run_name": batch.name,
            "task_id": member.task_id if member else None,
            "task_title": (revision.content or {}).get("title") if revision else None,
            "outcome": (revision.content or {}).get("outcome") if revision else None,
            "score": (revision.content or {}).get("score") if revision else None,
            "member_id": member.id if member else None,
        }
    )
    return item


@router.post("/api/jobs/{job_id}/retry")
def retry_job(
    job_id: str, body: StartBatch | None = None, db: Session = Depends(get_db), user: User = Depends(get_user)
):
    job = db.scalars(
        select(Job).where(Job.id == job_id).with_for_update().execution_options(populate_existing=True)
    ).first()
    if not job or job.workspace_id != user.workspace_id:
        raise HTTPException(404, "Job not found")
    batch, role = get_batch(db, job.batch_id, user, required_role="manager")
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Jobs in a cancelled batch cannot be retried")
    preset = db.get(PresetRevision, job.preset_revision_id)
    if not preset:
        raise HTTPException(409, "Pinned preset revision is missing")
    require_preset_budget_confirmation(preset, body)
    if job.status not in ("failed", "completed"):
        raise HTTPException(409, "Only failed or completed jobs can be retried")
    if job.attempt_count >= job.max_attempts:
        raise HTTPException(409, "Bounded retry limit has been reached")
    job.generation += 1
    job.fence_token += 1
    job.status = "queued"
    job.error = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.available_at = utcnow()
    job.updated_at = utcnow()
    job.idempotency_key = f"review:{job.member_id}:{job.preset_revision_id}:{job.generation}"
    db.add(OutboxEvent(job_id=job.id, generation=job.generation, status="pending"))
    member = db.get(BatchMember, job.member_id)
    if member:
        member.status = "queued"
    if batch.status != "paused":
        batch.status = "running"
    batch.updated_at = utcnow()
    activity(db, user, "job.retried", "job", job.id, generation=job.generation)
    db.commit()
    return record(job)
