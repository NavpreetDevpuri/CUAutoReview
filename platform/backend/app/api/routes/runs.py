"""Runs: create, configure, start, pause, resume, cancel, rerun, archive and task access."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_user
from app.api.routes.batches import batch_tasks, cancel_batch, get_batch_task, pause_batch, resume_batch, sync_batch
from app.core.database import get_db
from app.models import (
    Batch,
    BatchGrant,
    BatchMember,
    Dataset,
    Job,
    PresetRevision,
    RunConfiguration,
    RunSource,
    TaskDefinition,
    TaskRevision,
    Team,
    User,
    utcnow,
)
from app.schemas import RunConfigure, RunCreate, RunRerun, StartBatch
from app.services.access import get_batch, is_archived, need_batch_manager, require_dataset_access, set_archived
from app.services.audit import activity
from app.services.execution import execution_snapshot, require_preset_budget_confirmation, workflow_by_revision
from app.services.runs import (
    batch_execution_status,
    create_run_preset,
    create_run_records,
    enqueue_review_jobs,
    lock_batch_status,
)
from app.services.tasks import current_revision, task_definitions
from app.services.views import run_detail

router = APIRouter()


@router.post("/api/runs")
def create_run(body: RunCreate, db: Session = Depends(get_db), user: User = Depends(get_user)):
    if bool(body.dataset_ids) == bool(body.task_definition_ids):
        raise HTTPException(422, "Choose exactly one of dataset_ids or task_definition_ids")
    if body.dataset_ids and len(set(body.dataset_ids)) != len(body.dataset_ids):
        raise HTTPException(422, "dataset_ids must be unique")
    if body.task_definition_ids and len(set(body.task_definition_ids)) != len(body.task_definition_ids):
        raise HTTPException(422, "task_definition_ids must be unique")
    workflow = workflow_by_revision(body.workflow_revision_id)
    if body.dataset_ids:
        datasets_selected = [require_dataset_access(db, dataset_id, user, "manager") for dataset_id in body.dataset_ids]
        definitions = [
            definition
            for dataset in datasets_selected
            for definition in task_definitions(db, dataset.id)
            if not is_archived(db, "task", definition.id)
        ]
    else:
        definitions = []
        for definition_id in body.task_definition_ids or []:
            definition = db.get(TaskDefinition, definition_id)
            if not definition:
                raise HTTPException(404, "Task definition not found")
            require_dataset_access(db, definition.dataset_id, user, "manager")
            if is_archived(db, "task", definition.id):
                raise HTTPException(409, "Archived tasks cannot be added to a run")
            definitions.append(definition)
    if not definitions:
        raise HTTPException(422, "Run selection contains no active tasks")
    datasets_by_id: dict[str, Dataset] = {}
    selected_members = []
    for definition in definitions:
        dataset = db.get(Dataset, definition.dataset_id)
        if not dataset:
            continue
        datasets_by_id[dataset.id] = dataset
        revision = current_revision(db, definition)
        if revision:
            selected_members.append((definition, revision))
    if not selected_members:
        raise HTTPException(422, "Run selection contains no task revisions")
    execution = execution_snapshot(body.execution.model_dump(), workflow)
    batch = create_run_records(
        db,
        user,
        name=body.name,
        description=body.description,
        datasets=list(datasets_by_id.values()),
        members=selected_members,
        workflow=workflow,
        execution=execution,
        team_ids=body.team_ids,
        user_ids=body.user_ids,
    )
    activity(
        db,
        user,
        "run.created",
        "run",
        batch.id,
        task_count=len(selected_members),
        dataset_count=len(datasets_by_id),
        workflow_revision_id=workflow["revision_id"],
    )
    db.commit()
    return run_detail(db, batch, user)


@router.get("/api/runs")
def list_runs(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    rows = db.scalars(
        select(Batch).where(Batch.workspace_id == user.workspace_id).order_by(Batch.created_at.desc())
    ).all()
    visible = []
    for batch in rows:
        if not include_archived and is_archived(db, "run", batch.id):
            continue
        try:
            get_batch(db, batch.id, user)
            visible.append(batch)
        except HTTPException:
            continue
    size = min(max(per_page, 1), 200)
    start = max(page - 1, 0) * size
    return {"items": [run_detail(db, item, user) for item in visible[start : start + size]], "total": len(visible)}


@router.get("/api/runs/{run_id}")
def get_run(run_id: str, include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, _role = get_batch(db, run_id, user)
    if is_archived(db, "run", run_id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return run_detail(db, batch, user)


@router.post("/api/runs/{run_id}/configure")
def configure_run(run_id: str, body: RunConfigure, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    if batch.status != "draft" or db.scalar(select(func.count(Job.id)).where(Job.batch_id == batch.id)):
        raise HTTPException(409, "Run configuration is frozen after start")
    current_config = db.scalar(select(RunConfiguration).where(RunConfiguration.batch_id == batch.id))
    workflow = workflow_by_revision(
        body.workflow_revision_id or (current_config.workflow_revision_id if current_config else "trajectory_review@1")
    )
    pinned = db.get(PresetRevision, batch.preset_revision_id)
    current_execution = (
        (
            current_config.execution_snapshot
            if current_config
            else {
                "backend": pinned.backend,
                "model": pinned.model,
                "reasoning": pinned.reasoning,
                "budget_usd": pinned.budget_usd,
                "configuration": pinned.configuration,
            }
        )
        if pinned
        else {}
    )
    requested_execution = body.execution.model_dump() if body.execution else current_execution
    if "workflow_snapshot" in (requested_execution.get("configuration") or {}):
        requested_execution["configuration"] = {
            key: value for key, value in requested_execution["configuration"].items() if key != "workflow_snapshot"
        }
    execution = execution_snapshot(requested_execution, workflow)
    new_revision = create_run_preset(db, user, execution)
    batch.preset_revision_id = new_revision.id
    if not current_config:
        current_config = RunConfiguration(
            batch_id=batch.id,
            workflow_revision_id=workflow["revision_id"],
            workflow_snapshot=workflow,
            execution_snapshot=execution,
            revision=1,
        )
        db.add(current_config)
    else:
        current_config.workflow_revision_id = workflow["revision_id"]
        current_config.workflow_snapshot = workflow
        current_config.execution_snapshot = execution
        current_config.revision += 1
    activity(db, user, "run.configured", "run", batch.id, workflow_revision_id=workflow["revision_id"])
    db.commit()
    return run_detail(db, batch, user)


@router.post("/api/runs/{run_id}/start")
def start_run(
    run_id: str, body: StartBatch | None = None, db: Session = Depends(get_db), user: User = Depends(get_user)
):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Cancelled runs cannot be restarted; create a rerun")
    if batch.status == "paused":
        raise HTTPException(409, "Resume the paused run instead of starting it again")
    preset = db.get(PresetRevision, batch.preset_revision_id)
    if not preset:
        raise HTTPException(409, "Pinned execution snapshot is missing")
    require_preset_budget_confirmation(preset, body)
    added = enqueue_review_jobs(db, batch, user)
    batch.status = batch_execution_status(db, batch)
    batch.updated_at = utcnow()
    activity(
        db, user, "run.started", "run", batch.id, jobs_added=added, backend=preset.backend, budget_usd=preset.budget_usd
    )
    db.commit()
    return {**run_detail(db, batch, user), "jobs_added": added}


@router.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    cancel_batch(run_id, db, (batch, user, role))
    return run_detail(db, batch, user)


@router.post("/api/runs/{run_id}/pause")
def pause_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    pause_batch(run_id, db, (batch, user, role))
    return run_detail(db, batch, user)


@router.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    resume_batch(run_id, db, (batch, user, role))
    return run_detail(db, batch, user)


@router.post("/api/runs/{run_id}/sync")
def sync_run(run_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    result = sync_batch(run_id, request, db, (batch, user, role))
    return {**result, "run_id": run_id}


@router.get("/api/runs/{run_id}/tasks")
def run_tasks(
    run_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1),
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    batch, _role = get_batch(db, run_id, user)
    if is_archived(db, "run", batch.id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return batch_tasks(run_id, page, per_page, db, (batch, user, _role))


@router.get("/api/runs/{run_id}/tasks/{task_id}")
def get_run_task(
    run_id: str,
    task_id: str,
    member_id: str | None = None,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    batch, _role = get_batch(db, run_id, user)
    if is_archived(db, "run", batch.id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return get_batch_task(run_id, task_id, member_id, db, (batch, user, _role))


@router.post("/api/runs/{run_id}/archive")
def archive_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    return set_archived(db, user, "run", batch.id, True)


@router.post("/api/runs/{run_id}/restore")
def restore_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    return set_archived(db, user, "run", batch.id, False)


@router.post("/api/runs/{run_id}/rerun")
def rerun_run(run_id: str, body: RunRerun | None = None, db: Session = Depends(get_db), user: User = Depends(get_user)):
    source, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", source.id):
        raise HTTPException(409, "Archived runs cannot be rerun")
    body = body or RunRerun()
    current_config = db.scalar(select(RunConfiguration).where(RunConfiguration.batch_id == source.id))
    source_preset = db.get(PresetRevision, source.preset_revision_id)
    if not source_preset:
        raise HTTPException(409, "Source run execution snapshot is missing")
    source_workflow_id = current_config.workflow_revision_id if current_config else "trajectory_review@1"
    workflow = workflow_by_revision(body.workflow_revision_id or source_workflow_id)
    source_execution = (
        current_config.execution_snapshot
        if current_config
        else {
            "backend": source_preset.backend,
            "model": source_preset.model,
            "reasoning": source_preset.reasoning,
            "budget_usd": source_preset.budget_usd,
            "configuration": source_preset.configuration,
        }
    )
    if "workflow_snapshot" in (source_execution.get("configuration") or {}):
        source_execution = copy.deepcopy(source_execution)
        source_execution["configuration"] = {
            key: value for key, value in source_execution["configuration"].items() if key != "workflow_snapshot"
        }
    execution = execution_snapshot(body.execution.model_dump() if body.execution else source_execution, workflow)
    sources = list(
        db.scalars(
            select(RunSource.dataset_id).where(RunSource.batch_id == source.id).order_by(RunSource.position)
        ).all()
    ) or [source.dataset_id]
    datasets_selected = [require_dataset_access(db, dataset_id, user, "manager") for dataset_id in sources]
    members = db.scalars(
        select(BatchMember).where(BatchMember.batch_id == source.id).order_by(BatchMember.created_at)
    ).all()
    selected = []
    for member in members:
        definition, revision = (
            db.get(TaskDefinition, member.task_definition_id),
            db.get(TaskRevision, member.task_revision_id),
        )
        if definition and revision:
            selected.append((definition, revision))
    if not selected:
        raise HTTPException(422, "Source run has no task revisions to rerun")
    grants = db.scalars(select(BatchGrant).where(BatchGrant.batch_id == source.id)).all()
    new_run = create_run_records(
        db,
        user,
        name=body.name or f"Rerun: {source.name}",
        description=source.description,
        datasets=datasets_selected,
        members=selected,
        workflow=workflow,
        execution=execution,
        rerun_of=source.id,
    )
    # Carry each grant over with its original role; deactivated users or removed teams are skipped.
    for grant in grants:
        target = db.get(Team, grant.team_id) if grant.team_id else db.get(User, grant.user_id)
        if not target or target.workspace_id != user.workspace_id or getattr(target, "active", True) is False:
            continue
        db.add(
            BatchGrant(
                batch_id=new_run.id, team_id=grant.team_id, user_id=grant.user_id, role=grant.role, created_by=user.id
            )
        )
    activity(db, user, "run.rerun_created", "run", new_run.id, source_run_id=source.id)
    db.commit()
    return run_detail(db, new_run, user)
