"""Run creation, membership, review job admission and run status locking."""

from __future__ import annotations

import copy
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config
from app.models import (
    Batch,
    BatchGrant,
    BatchMember,
    Dataset,
    Job,
    OutboxEvent,
    Preset,
    PresetRevision,
    ProposalRevision,
    ReviewResult,
    RunConfiguration,
    RunSource,
    SyncWave,
    TaskDefinition,
    TaskRevision,
    TaxonomyProposal,
    TaxonomyRelease,
    Team,
    User,
    uid,
)
from app.services.evidence import register_evidence
from app.services.records import digest
from app.services.taxonomy import current_release
from app.services.views import member_review
from app.services.zip_import import copy_revision_artifacts_to_member


def create_run_preset(db: Session, user: User, snapshot: dict[str, Any]) -> PresetRevision:
    preset = Preset(workspace_id=user.workspace_id, name="__run_config__" + uid(), created_by=user.id)
    db.add(preset)
    db.flush()
    revision = PresetRevision(
        preset_id=preset.id,
        revision=1,
        backend=snapshot["backend"],
        model=snapshot["model"],
        reasoning=snapshot["reasoning"],
        budget_usd=snapshot["budget_usd"],
        configuration=copy.deepcopy(snapshot["configuration"]),
        config_hash=digest(snapshot),
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    return revision


def add_member(
    db: Session,
    batch: Batch,
    definition: TaskDefinition,
    revision: TaskRevision,
    wave_id: str,
    user: User,
    status: str | None = None,
) -> BatchMember:
    existing = db.scalar(
        select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_revision_id == revision.id)
    )
    if existing:
        return existing
    content = revision.content
    route = (
        "failure_analysis"
        if content.get("outcome") == "failed"
        else "pass_recovery"
        if content.get("outcome") == "passed"
        else None
    )
    review = content.get("review")
    member_status = status or "awaiting_review"
    member = BatchMember(
        batch_id=batch.id,
        task_definition_id=definition.id,
        task_revision_id=revision.id,
        wave_id=wave_id,
        task_id=definition.task_id,
        review_kind=route,
        status=member_status,
    )
    db.add(member)
    db.flush()
    if review and member_status == "completed":
        preset = db.get(PresetRevision, batch.preset_revision_id)
        db.add(
            ReviewResult(
                member_id=member.id,
                revision=1,
                review_kind=route or review.get("review_kind", "unknown"),
                schema_version=review.get("schema_version"),
                source_kind="saved_replay",
                backend="saved_replay",
                model=content.get("original_model") or "model not recorded",
                review=copy.deepcopy(review),
                provenance={
                    "mode": "saved_replay",
                    "original_run_id": content.get("original_run_id")
                    or (content.get("provenance") or {}).get("run_id"),
                    "original_model": content.get("original_model"),
                    "original_reasoning_effort": content.get("original_reasoning_effort"),
                    "original_usage": content.get("usage"),
                    "original_prompt_sha256": content.get("original_prompt_sha256"),
                    "new_inference": False,
                    "preset_revision_id": preset.id if preset else None,
                },
            )
        )
    # Carry dataset-revision ZIP evidence into a member-scoped authorization row.
    copy_revision_artifacts_to_member(db, user.workspace_id, revision, member)
    db.flush()
    register_evidence(db, user, revision, member, content)
    return member


def create_run_records(
    db: Session,
    user: User,
    *,
    name: str,
    description: str,
    datasets: list[Dataset],
    members: list[tuple[TaskDefinition, TaskRevision]],
    workflow: dict[str, Any],
    execution: dict[str, Any],
    team_ids: list[str] | None = None,
    user_ids: list[str] | None = None,
    rerun_of: str | None = None,
) -> Batch:
    preset_revision = create_run_preset(db, user, execution)
    batch = Batch(
        workspace_id=user.workspace_id,
        dataset_id=datasets[0].id,
        name=name.strip(),
        description=description,
        mode="fixed",
        preset_revision_id=preset_revision.id,
        taxonomy_release_id=(
            current_release(db, user.workspace_id).id if current_release(db, user.workspace_id) else None
        ),
        status="draft",
        created_by=user.id,
    )
    db.add(batch)
    db.flush()
    for position, dataset in enumerate(datasets):
        db.add(RunSource(batch_id=batch.id, dataset_id=dataset.id, position=position))
    config = RunConfiguration(
        batch_id=batch.id,
        workflow_revision_id=workflow["revision_id"],
        workflow_snapshot=copy.deepcopy(workflow),
        execution_snapshot=copy.deepcopy(execution),
        rerun_of_batch_id=rerun_of,
    )
    db.add(config)
    db.flush()
    wave = SyncWave(batch_id=batch.id, number=1, sync_key="initial", task_count=len(members), created_by=user.id)
    db.add(wave)
    db.flush()
    for definition, revision in members:
        add_member(db, batch, definition, revision, wave.id, user)
    for team_id in team_ids or []:
        team = db.get(Team, team_id)
        if not team or team.workspace_id != user.workspace_id:
            raise HTTPException(404, "Workspace team not found")
        db.add(BatchGrant(batch_id=batch.id, team_id=team.id, role="reviewer", created_by=user.id))
    for user_id in user_ids or []:
        target = db.get(User, user_id)
        if not target or not target.active or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "Active workspace user not found")
        db.add(BatchGrant(batch_id=batch.id, user_id=target.id, role="reviewer", created_by=user.id))
    return batch


def enqueue_review_jobs(db: Session, batch: Batch, user: User):
    preset_revision = db.get(PresetRevision, batch.preset_revision_id)
    if not preset_revision:
        raise HTTPException(409, "Pinned preset revision is missing")
    members = db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id)).all()
    shared_labels = []
    release = db.get(TaxonomyRelease, batch.taxonomy_release_id) if batch.taxonomy_release_id else None
    if release:
        shared_labels.extend(copy.deepcopy((release.content or {}).get("labels", [])))
    known = {str(item.get("id")) for item in shared_labels if isinstance(item, dict) and item.get("id")}
    proposals = db.scalars(
        select(TaxonomyProposal)
        .where(TaxonomyProposal.workspace_id == batch.workspace_id)
        .order_by(TaxonomyProposal.created_at)
    ).all()
    for proposal in proposals:
        revision = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if not revision:
            continue
        label_id = proposal.label_id or f"draft:{proposal.id}"
        if str(label_id) in known:
            continue
        shared_labels.append(
            {"id": label_id, "name": revision.name, "description": revision.description, "status": "draft"}
        )
        known.add(str(label_id))
    added = 0
    for member in members:
        if member.status == "completed" and member_review(db, member):
            continue
        revision = db.get(TaskRevision, member.task_revision_id)
        content = revision.content if revision else {}
        outcome = content.get("outcome")
        route = "failure_analysis" if outcome == "failed" else "pass_recovery" if outcome == "passed" else None
        if route is None:
            member.status = "awaiting_review"
            continue
        member.review_kind = route
        idem = f"review:{member.id}:{preset_revision.id}:1"
        # Manual retries reuse the job and bump the key's generation suffix, so match the
        # member and pinned preset instead of the first-generation key.
        old = db.scalar(
            select(Job.id)
            .where(Job.member_id == member.id, Job.stage == "review", Job.preset_revision_id == preset_revision.id)
            .limit(1)
        )
        if old:
            continue
        job = Job(
            workspace_id=user.workspace_id,
            batch_id=batch.id,
            member_id=member.id,
            stage="review",
            review_kind=route,
            preset_revision_id=preset_revision.id,
            idempotency_key=idem,
            generation=1,
            fence_token=0,
            status="queued",
            max_attempts=min(4, max(1, int(config.settings.max_job_attempts))),
            shared_labels_snapshot=copy.deepcopy(shared_labels),
        )
        db.add(job)
        db.flush()
        db.add(OutboxEvent(job_id=job.id, generation=job.generation, status="pending"))
        member.status = "queued"
        added += 1
    return added


def batch_execution_status(db: Session, batch: Batch) -> str:
    if batch.status in ("paused", "cancelled"):
        return batch.status
    active_jobs = (
        db.scalar(
            select(func.count(Job.id)).where(
                Job.batch_id == batch.id, Job.status.in_(("queued", "running", "retrying"))
            )
        )
        or 0
    )
    if active_jobs:
        return "running"
    statuses = db.scalars(select(BatchMember.status).where(BatchMember.batch_id == batch.id)).all()
    if any(status not in ("completed", "failed", "cancelled", "awaiting_review") for status in statuses):
        # A member without an active job is still unresolved. Keep the batch open so
        # an inconsistent member/job pair cannot be mistaken for a finished run.
        return "running"
    if any(status == "awaiting_review" for status in statuses):
        return "awaiting_review"
    return "completed"


def lock_batch_status(db: Session, batch: Batch) -> Batch:
    """Refresh and serialize an execution-state transition on its batch row."""
    return (
        db.scalars(
            select(Batch).where(Batch.id == batch.id).with_for_update().execution_options(populate_existing=True)
        ).first()
        or batch
    )
