"""Legacy batch endpoints and run actions shared with the /api/runs aliases."""

from __future__ import annotations

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_user, require_batch, require_role
from app.core.database import get_db
from app.models import (
    Batch,
    BatchGrant,
    BatchMember,
    Dataset,
    Job,
    JobAttempt,
    OutboxEvent,
    Preset,
    PresetRevision,
    SyncWave,
    TaskDefinition,
    TaskFeedback,
    TaskRevision,
    Team,
    User,
    utcnow,
)
from app.schemas import BatchCreate, BatchGrantCreate, FeedbackCreate, StartBatch
from app.services.access import get_batch, is_archived, need_batch_manager
from app.services.audit import activity
from app.services.execution import require_preset_budget_confirmation
from app.services.read_cache import preload_artifacts, preload_members, preload_rows
from app.services.records import digest, record
from app.services.runs import add_member, batch_execution_status, enqueue_review_jobs, lock_batch_status
from app.services.tasks import current_revision, task_definitions
from app.services.taxonomy import current_release
from app.services.views import batch_detail, member_review, task_view

router = APIRouter()


@router.get("/api/batches")
def batches(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    query = select(Batch).where(Batch.workspace_id == user.workspace_id).order_by(Batch.created_at.desc())
    all_items = db.scalars(query).all()
    visible = []
    for batch in all_items:
        if not include_archived and is_archived(db, "run", batch.id):
            continue
        try:
            get_batch(db, batch.id, user)
            visible.append(batch)
        except HTTPException:
            pass
    start = max(page - 1, 0) * min(per_page, 200)
    return {"items": [batch_detail(db, b) for b in visible[start : start + min(per_page, 200)]], "total": len(visible)}


@router.post("/api/batches")
def create_batch(
    body: BatchCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))
):
    dataset = db.get(Dataset, body.dataset_id)
    preset = db.get(Preset, body.preset_id)
    if not dataset or dataset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Dataset not found")
    if not preset or preset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Preset not found")
    preset_revision = db.scalar(
        select(PresetRevision).where(PresetRevision.preset_id == preset.id).order_by(PresetRevision.revision.desc())
    )
    if not preset_revision:
        raise HTTPException(409, "Preset has no immutable revision")
    definitions = {d.task_id: d for d in task_definitions(db, dataset.id)}
    selected = body.task_ids if body.task_ids is not None else list(definitions)
    if len(set(selected)) != len(selected):
        raise HTTPException(422, "task_ids must be unique")
    unknown = sorted(set(selected) - set(definitions))
    if unknown:
        raise HTTPException(404, f"Unknown task IDs: {', '.join(unknown[:5])}")
    release = current_release(db, user.workspace_id)
    batch = Batch(
        workspace_id=user.workspace_id,
        dataset_id=dataset.id,
        name=body.name.strip(),
        description=body.description,
        mode=body.mode,
        preset_revision_id=preset_revision.id,
        taxonomy_release_id=release.id if release else None,
        status="draft",
        created_by=user.id,
    )
    db.add(batch)
    db.flush()
    wave = SyncWave(batch_id=batch.id, number=1, sync_key="initial", task_count=len(selected), created_by=user.id)
    db.add(wave)
    db.flush()
    for task_id in selected:
        definition = definitions[task_id]
        revision = current_revision(db, definition)
        if revision:
            add_member(db, batch, definition, revision, wave.id, user)
    for team_id in body.team_ids:
        team = db.get(Team, team_id)
        if not team or team.workspace_id != user.workspace_id:
            raise HTTPException(404, "Team not found")
        db.add(BatchGrant(batch_id=batch.id, team_id=team.id, role="reviewer", created_by=user.id))
    activity(db, user, "batch.created", "batch", batch.id, member_count=len(selected), mode=batch.mode)
    db.commit()
    return batch_detail(db, batch)


@router.get("/api/batches/{batch_id}")
def get_batch_detail(
    batch_id: str, include_archived: bool = False, db: Session = Depends(get_db), access=Depends(require_batch())
):
    batch, user, _role = access
    if is_archived(db, "run", batch.id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return batch_detail(db, db.get(Batch, batch.id))


@router.get("/api/batches/{batch_id}/tasks")
def batch_tasks(
    batch_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1),
    db: Session = Depends(get_db),
    access=Depends(require_batch()),
):
    batch, user, _role = access
    query = (
        select(BatchMember)
        .where(BatchMember.batch_id == batch.id)
        .order_by(BatchMember.created_at, BatchMember.task_id)
    )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    size = min(per_page, 500)
    members = db.scalars(query.offset((page - 1) * size).limit(size)).all()
    preload_members(db, members)
    preload_artifacts(db, member_ids=[member.id for member in members])
    preload_rows(db, TaskDefinition, {member.task_definition_id for member in members})
    items = []
    for member in members:
        revision = db.get(TaskRevision, member.task_revision_id)
        if revision:
            items.append(
                task_view(
                    db,
                    revision.content,
                    revision.id,
                    member.task_id,
                    revision.revision,
                    member,
                    member_review(db, member),
                )
            )
    return {"items": items, "total": total}


@router.get("/api/batches/{batch_id}/tasks/{task_id}")
def get_batch_task(
    batch_id: str,
    task_id: str,
    member_id: str | None = None,
    db: Session = Depends(get_db),
    access=Depends(require_batch()),
):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    revision = db.get(TaskRevision, member.task_revision_id)
    task = task_view(db, revision.content, revision.id, task_id, revision.revision, member, member_review(db, member))
    feedback = db.scalars(
        select(TaskFeedback).where(TaskFeedback.member_id == member.id).order_by(TaskFeedback.created_at)
    ).all()
    return {
        **task,
        "member": {
            "id": member.id,
            "batch_id": batch.id,
            "task_id": task_id,
            "status": member.status,
            "processing_status": member.status,
            "review_kind": member.review_kind,
        },
        "task": task,
        "review": task.get("review"),
        "review_history": task.get("review_history", []),
        "feedback": [record(item) for item in feedback],
    }


@router.post("/api/batches/{batch_id}/sync")
def sync_batch(
    batch_id: str, request: Request, db: Session = Depends(get_db), access=Depends(require_batch("manager"))
):
    batch, user, role = access
    need_batch_manager(role)
    if batch.mode != "appendable":
        raise HTTPException(409, "Fixed batches cannot append tasks")
    key = request.headers.get("Idempotency-Key") or request.query_params.get("sync_key")
    if not key:
        latest_ids = [
            (d.task_id, current_revision(db, d).id if current_revision(db, d) else None)
            for d in task_definitions(db, batch.dataset_id)
        ]
        key = "snapshot-" + digest(latest_ids)
    if len(key) > 200:
        raise HTTPException(422, "Sync key too long")
    old = db.scalar(select(SyncWave).where(SyncWave.batch_id == batch.id, SyncWave.sync_key == key))
    if old:
        return {"wave": record(old), "added": 0, "idempotent_replay": True}
    existing = set(db.scalars(select(BatchMember.task_revision_id).where(BatchMember.batch_id == batch.id)).all())
    definitions = task_definitions(db, batch.dataset_id)
    new = [(d, current_revision(db, d)) for d in definitions]
    new = [(d, r) for d, r in new if r and r.id not in existing]
    wave_number = (db.scalar(select(func.max(SyncWave.number)).where(SyncWave.batch_id == batch.id)) or 0) + 1
    wave = SyncWave(batch_id=batch.id, number=wave_number, sync_key=key, task_count=len(new), created_by=user.id)
    db.add(wave)
    db.flush()
    for definition, revision in new:
        add_member(db, batch, definition, revision, wave.id, user)
    batch.updated_at = utcnow()
    activity(db, user, "batch.synced", "batch", batch.id, wave_number=wave_number, added=len(new), sync_key=key)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent duplicate delivery resolves to the already committed immutable wave.
        old = db.scalar(select(SyncWave).where(SyncWave.batch_id == batch.id, SyncWave.sync_key == key))
        if old:
            return {"wave": record(old), "added": 0, "idempotent_replay": True}
        raise HTTPException(409, "Concurrent sync conflict; retry with the same key") from None
    return {"wave": record(wave), "added": len(new), "idempotent_replay": False}


@router.post("/api/batches/{batch_id}/grants")
@router.post("/api/runs/{batch_id}/grants")
def create_batch_grant(
    batch_id: str, body: BatchGrantCreate, db: Session = Depends(get_db), access=Depends(require_batch("manager"))
):
    batch, user, role = access
    need_batch_manager(role)
    if bool(body.team_id) == bool(body.user_id):
        raise HTTPException(422, "Provide exactly one of team_id or user_id")
    if body.team_id:
        target = db.get(Team, body.team_id)
        if not target or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "Team not found")
    else:
        target = db.get(User, body.user_id)
        if not target or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "User not found")
    grant = BatchGrant(
        batch_id=batch.id, team_id=body.team_id, user_id=body.user_id, role=body.role, created_by=user.id
    )
    db.add(grant)
    activity(
        db,
        user,
        "batch.grant_created",
        "batch",
        batch.id,
        grant_role=body.role,
        team_id=body.team_id,
        user_id=body.user_id,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        grant = db.scalar(
            select(BatchGrant).where(
                BatchGrant.batch_id == batch.id,
                BatchGrant.team_id == body.team_id if body.team_id else BatchGrant.team_id.is_(None),
                BatchGrant.user_id == body.user_id if body.user_id else BatchGrant.user_id.is_(None),
                BatchGrant.role == body.role,
            )
        )
    return record(grant)


@router.delete("/api/batches/{batch_id}/grants/{grant_id}", status_code=204)
@router.delete("/api/runs/{batch_id}/grants/{grant_id}", status_code=204)
def delete_batch_grant(
    batch_id: str, grant_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))
):
    batch, user, role = access
    need_batch_manager(role)
    grant = db.get(BatchGrant, grant_id)
    if not grant or grant.batch_id != batch.id:
        raise HTTPException(404, "Grant not found")
    db.delete(grant)
    activity(db, user, "batch.grant_revoked", "batch", batch.id, grant_id=grant_id)
    db.commit()


@router.post("/api/batches/{batch_id}/start")
def start_batch(
    batch_id: str,
    body: StartBatch | None = None,
    db: Session = Depends(get_db),
    access=Depends(require_batch("manager")),
):
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Cancelled batches cannot be restarted")
    if batch.status == "paused":
        raise HTTPException(409, "Resume the paused batch instead of starting it again")
    preset = db.get(PresetRevision, batch.preset_revision_id)
    if not preset:
        raise HTTPException(409, "Pinned preset revision is missing")
    require_preset_budget_confirmation(preset, body)
    added = enqueue_review_jobs(db, batch, user)
    batch.status = batch_execution_status(db, batch)
    batch.updated_at = utcnow()
    activity(
        db,
        user,
        "batch.started",
        "batch",
        batch.id,
        jobs_added=added,
        backend=preset.backend,
        budget_usd=preset.budget_usd,
    )
    db.commit()
    return {**batch_detail(db, batch), "jobs_added": added}


@router.post("/api/batches/{batch_id}/pause")
def pause_batch(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status != "running":
        raise HTTPException(409, "Only a running batch can be paused")
    batch.status = "paused"
    batch.updated_at = utcnow()
    # Jobs that have not been delivered stay queued; outbox relay skips paused batches.
    activity(db, user, "batch.paused", "batch", batch.id)
    db.commit()
    return batch_detail(db, batch)


@router.post("/api/batches/{batch_id}/resume")
def resume_batch(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Cancelled batches cannot be resumed")
    if batch.status not in ("paused", "running"):
        raise HTTPException(409, "Only a paused batch can be resumed")
    batch.status = "running"
    batch.updated_at = utcnow()
    for job in db.scalars(select(Job).where(Job.batch_id == batch.id, Job.status.in_(("queued", "retrying")))).all():
        event = db.scalar(
            select(OutboxEvent).where(OutboxEvent.job_id == job.id, OutboxEvent.generation == job.generation)
        )
        if not event:
            event = OutboxEvent(job_id=job.id, generation=job.generation, status="pending")
            db.add(event)
        else:
            event.status = "pending"
        event.available_at = utcnow()
        job.available_at = utcnow()
        event.relay_owner = None
        event.relay_lease_expires_at = None
        event.sent_at = None
        event.last_error = None
    batch.status = batch_execution_status(db, batch)
    activity(db, user, "batch.resumed", "batch", batch.id)
    db.commit()
    return batch_detail(db, batch)


@router.post("/api/batches/{batch_id}/reconcile")
@router.post("/api/runs/{batch_id}/reconcile")
def reconcile_batch_status(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    """Explicitly repair a stale running status when persisted work is terminal."""
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    previous = batch.status
    derived = batch_execution_status(db, batch)
    if previous != "running" or derived not in ("completed", "awaiting_review"):
        return {
            **batch_detail(db, batch),
            "reconciled": False,
            "reconcile_reason": f"Stored status is {previous}; authoritative work state is {derived}.",
        }
    batch.status = derived
    batch.updated_at = utcnow()
    activity(db, user, "batch.status_reconciled", "batch", batch.id, previous_status=previous, status=derived)
    db.commit()
    return {**batch_detail(db, batch), "reconciled": True, "previous_status": previous}


@router.post("/api/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    # Workers lock their job before the batch row. Keep the same order here so a
    # cancellation cannot deadlock with a worker committing its final result.
    jobs = db.scalars(
        select(Job)
        .where(Job.batch_id == batch.id)
        .order_by(Job.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    batch = lock_batch_status(db, batch)
    if batch.status == "completed":
        raise HTTPException(409, "Completed batches cannot be cancelled")
    if batch.status == "cancelled":
        return batch_detail(db, batch)
    batch.status = "cancelled"
    batch.updated_at = utcnow()
    now = utcnow()
    cancelled_jobs = 0
    for job in jobs:
        if job.status not in ("queued", "running", "retrying"):
            continue
        old_generation, old_fence = job.generation, job.fence_token
        was_running = job.status == "running"
        job.status = "cancelled"
        job.generation += 1
        job.fence_token += 1
        job.updated_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.error = (
            "Cancelled while active; completion and provider usage are unknown."
            if was_running
            else "Cancelled before dispatch."
        )
        if was_running:
            job.usage = {"kind": "unknown", "estimated_usd": None}
            job.cost_usd = None
            attempt = db.scalar(
                select(JobAttempt)
                .where(
                    JobAttempt.job_id == job.id,
                    JobAttempt.generation == old_generation,
                    JobAttempt.fence_token == old_fence,
                    JobAttempt.status == "running",
                )
                .with_for_update()
            )
            if attempt:
                attempt.status = "cancelled"
                attempt.error = job.error
                attempt.usage = {"kind": "unknown", "estimated_usd": None}
                attempt.cost_usd = None
                attempt.finished_at = now
        member = db.get(BatchMember, job.member_id)
        if member:
            member.status = "cancelled"
        for event in db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.job_id == job.id,
                OutboxEvent.generation == old_generation,
                OutboxEvent.status.in_(("pending", "sending")),
            )
        ):
            event.status = "cancelled"
        cancelled_jobs += 1
    cancelled_members = 0
    for member in db.scalars(
        select(BatchMember).where(
            BatchMember.batch_id == batch.id, BatchMember.status.not_in(("completed", "failed", "cancelled"))
        )
    ):
        member.status = "cancelled"
        cancelled_members += 1
    activity(
        db,
        user,
        "batch.cancelled",
        "batch",
        batch.id,
        cancelled_jobs=cancelled_jobs,
        cancelled_members=cancelled_members,
    )
    db.commit()
    return batch_detail(db, batch)


@router.post("/api/batches/{batch_id}/tasks/{task_id}/feedback")
@router.post("/api/runs/{batch_id}/tasks/{task_id}/feedback")
def create_task_feedback(
    batch_id: str,
    task_id: str,
    body: FeedbackCreate,
    member_id: str | None = None,
    db: Session = Depends(get_db),
    access=Depends(require_batch("reviewer")),
):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    feedback = TaskFeedback(
        member_id=member.id, author_id=user.id, text=body.text.strip(), step_id=body.step_id, episode_id=body.episode_id
    )
    db.add(feedback)
    activity(
        db, user, "task.feedback_added", "batch_member", member.id, step_id=body.step_id, episode_id=body.episode_id
    )
    db.commit()
    return record(feedback)


@router.get("/api/batches/{batch_id}/tasks/{task_id}/feedback")
@router.get("/api/runs/{batch_id}/tasks/{task_id}/feedback")
def list_task_feedback(
    batch_id: str,
    task_id: str,
    member_id: str | None = None,
    db: Session = Depends(get_db),
    access=Depends(require_batch()),
):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    items = db.scalars(
        select(TaskFeedback).where(TaskFeedback.member_id == member.id).order_by(TaskFeedback.created_at)
    ).all()
    return {"items": [record(f) for f in items], "total": len(items)}


@router.get("/api/batches/{batch_id}/tasks/{task_id}/export")
@router.get("/api/runs/{batch_id}/tasks/{task_id}/export")
def export_task(
    batch_id: str,
    task_id: str,
    format: str = Query("json", pattern="^(json|yaml)$"),
    member_id: str | None = None,
    db: Session = Depends(get_db),
    access=Depends(require_batch()),
):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    revision = db.get(TaskRevision, member.task_revision_id)
    result = task_view(db, revision.content, revision.id, task_id, revision.revision, member, member_review(db, member))
    if format == "yaml":
        return PlainTextResponse(
            yaml.safe_dump(result, allow_unicode=True, sort_keys=False), media_type="application/yaml"
        )
    return result
