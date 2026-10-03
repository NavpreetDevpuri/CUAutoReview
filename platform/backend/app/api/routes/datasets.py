"""Datasets, dataset sharing, archive state and per-task history and export."""

from __future__ import annotations

import copy
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_user, require_role
from app.core.database import get_db
from app.models import (
    Batch,
    BatchMember,
    Dataset,
    DatasetShare,
    ObjectArchive,
    RunSource,
    TaskDefinition,
    TaskRevision,
    Team,
    User,
    uid,
)
from app.schemas import DatasetCreate, DatasetSharesUpdate
from app.services.access import (
    can_view_batch,
    dataset_role,
    get_batch,
    is_archived,
    require_dataset_access,
    set_archived,
)
from app.services.audit import activity
from app.services.read_cache import (
    archived_objects,
    member_jobs,
    member_reviews,
    preload_artifacts,
    preload_members,
    preload_rows,
)
from app.services.records import iso, record
from app.services.tasks import current_revision, task_definitions
from app.services.views import (
    batch_detail,
    batch_members_by_batch,
    dataset_task_summary,
    job_detail,
    review_counts,
    review_evidence,
    task_view,
)

router = APIRouter()


@router.get("/api/datasets")
def datasets(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    query = select(Dataset).where(Dataset.workspace_id == user.workspace_id)
    all_items = db.scalars(query.order_by(Dataset.updated_at.desc())).all()
    visible = [
        d for d in all_items if dataset_role(db, d, user) and (include_archived or not is_archived(db, "dataset", d.id))
    ]
    total = len(visible)
    items = visible[max(page - 1, 0) * min(per_page, 200) : max(page - 1, 0) * min(per_page, 200) + min(per_page, 200)]
    output = []
    for d in items:
        item = record(d)
        item["archived"] = is_archived(db, "dataset", d.id)
        definitions = db.scalars(select(TaskDefinition).where(TaskDefinition.dataset_id == d.id)).all()
        if not include_archived:
            definitions = [definition for definition in definitions if not is_archived(db, "task", definition.id)]
        item["task_count"] = len(definitions)
        batches_for_dataset = db.scalars(
            select(Batch)
            .outerjoin(RunSource, RunSource.batch_id == Batch.id)
            .where(Batch.workspace_id == user.workspace_id, or_(Batch.dataset_id == d.id, RunSource.dataset_id == d.id))
            .order_by(Batch.created_at.desc())
            .distinct()
        ).all()
        dataset_batches = [
            b
            for b in batches_for_dataset
            if can_view_batch(db, b.id, user) and (include_archived or not is_archived(db, "run", b.id))
        ]
        covered = db.scalars(
            select(BatchMember.task_definition_id)
            .join(TaskDefinition, TaskDefinition.id == BatchMember.task_definition_id)
            .where(
                TaskDefinition.dataset_id == d.id,
                BatchMember.batch_id.in_([b.id for b in dataset_batches]) if dataset_batches else False,
            )
        ).all()
        item["run_count"] = len(dataset_batches)
        item["membership_coverage"] = {"tasks_in_runs": len(set(covered)), "tasks_total": len(definitions)}
        item["batches"] = [batch_detail(db, b) for b in dataset_batches]
        output.append(item)
    return {"items": output, "total": total}


@router.post("/api/datasets")
def create_dataset(
    body: DatasetCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))
):
    dataset = Dataset(
        id=uid(),
        workspace_id=user.workspace_id,
        name=body.name.strip(),
        description=body.description,
        source_adapter=body.source_adapter,
        created_by=user.id,
    )
    db.add(dataset)
    activity(db, user, "dataset.created", "dataset", dataset.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A dataset with that name already exists") from None
    return record(dataset)


@router.get("/api/datasets/{dataset_id}")
def dataset_detail(
    dataset_id: str, include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_user)
):
    dataset = require_dataset_access(db, dataset_id, user, include_archived=include_archived)
    output = record(dataset)
    output["archived"] = is_archived(db, "dataset", dataset.id)
    # Lets the UI hide controls the caller cannot use, such as sharing (manager or above).
    output["access_role"] = dataset_role(db, dataset, user)
    tasks = []
    definitions = task_definitions(db, dataset.id)
    preload_rows(db, TaskRevision, {definition.current_revision_id for definition in definitions})
    preload_artifacts(db, revision_ids=[definition.current_revision_id for definition in definitions])
    for definition in definitions:
        if not include_archived and is_archived(db, "task", definition.id):
            continue
        rev = current_revision(db, definition)
        if rev:
            item = task_view(db, rev.content, rev.id, definition.task_id, rev.revision)
            item["task_definition_id"] = definition.id
            item["archived_at"] = archived_objects(db, "task").get(definition.id)
            if item["archived_at"]:
                item["archived_at"] = iso(item["archived_at"])
            tasks.append(item)
    batches_for_dataset = db.scalars(
        select(Batch)
        .outerjoin(RunSource, RunSource.batch_id == Batch.id)
        .where(
            Batch.workspace_id == user.workspace_id,
            or_(Batch.dataset_id == dataset.id, RunSource.dataset_id == dataset.id),
        )
        .order_by(Batch.created_at.desc())
        .distinct()
    ).all()
    batches = [
        batch
        for batch in batches_for_dataset
        if can_view_batch(db, batch.id, user) and (include_archived or not is_archived(db, "run", batch.id))
    ]
    visible_task_ids = {item["task_definition_id"] for item in tasks}
    members_by_run_task: dict[tuple[str, str], list[BatchMember]] = {}
    for batch_id, members in batch_members_by_batch(db, batches).items():
        for member in members:
            members_by_run_task.setdefault((batch_id, member.task_definition_id), []).append(member)
    preload_members(
        db,
        [
            member
            for (_batch_id, definition_id), members in members_by_run_task.items()
            if definition_id in visible_task_ids
            for member in members
        ],
    )
    included_by_run: dict[str, set[str]] = {}
    batch_outputs = []
    for batch in batches:
        included_ids = (
            set(
                db.scalars(
                    select(BatchMember.task_definition_id)
                    .join(TaskDefinition, TaskDefinition.id == BatchMember.task_definition_id)
                    .where(BatchMember.batch_id == batch.id, TaskDefinition.dataset_id == dataset.id)
                ).all()
            )
            & visible_task_ids
        )
        included_by_run[batch.id] = included_ids
        item = batch_detail(db, batch)
        item["selected_task_count"] = len(included_ids)
        item["dataset_task_count"] = len(tasks)
        batch_outputs.append(item)
    for item in tasks:
        definition_id = item["task_definition_id"]
        memberships = []
        for batch_id, included_ids in included_by_run.items():
            if definition_id in included_ids:
                memberships.extend(members_by_run_task.get((batch_id, definition_id), []))
        item["summary"] = dataset_task_summary(db, item, memberships)
    output["tasks"] = tasks
    output["batches"] = batch_outputs
    output["run_count"] = len(batches)
    output["membership_coverage"] = {
        "tasks_in_runs": len(set().union(*included_by_run.values())) if included_by_run else 0,
        "tasks_total": len(tasks),
    }
    return output


def dataset_shares_response(db: Session, dataset: Dataset) -> dict[str, Any]:
    shares = db.scalars(
        select(DatasetShare).where(
            DatasetShare.dataset_id == dataset.id, DatasetShare.workspace_id == dataset.workspace_id
        )
    ).all()
    users_out, teams_out = [], []
    workspace_shared = False
    for share in shares:
        if share.target_type == "workspace":
            workspace_shared = True
        elif share.target_type == "user":
            target = db.get(User, share.target_id)
            if target and target.active:
                users_out.append({"user_id": target.id, "name": target.name, "email": target.email, "role": share.role})
        elif share.target_type == "team":
            target = db.get(Team, share.target_id)
            if target:
                teams_out.append({"team_id": target.id, "name": target.name, "role": share.role})
    return {"workspace_shared": workspace_shared, "users": users_out, "teams": teams_out}


@router.get("/api/datasets/{dataset_id}/shares")
def get_dataset_shares(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    return dataset_shares_response(db, dataset)


@router.put("/api/datasets/{dataset_id}/shares")
def put_dataset_shares(
    dataset_id: str, body: DatasetSharesUpdate, db: Session = Depends(get_db), user: User = Depends(get_user)
):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    if len({item.target_id for item in body.users}) != len(body.users) or len(
        {item.target_id for item in body.teams}
    ) != len(body.teams):
        raise HTTPException(422, "Share targets must be unique")
    for item in body.users:
        target = db.get(User, item.target_id)
        if not target or not target.active or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "Active workspace user not found")
    for item in body.teams:
        target = db.get(Team, item.target_id)
        if not target or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "Workspace team not found")
    db.query(DatasetShare).filter(DatasetShare.dataset_id == dataset.id).delete(synchronize_session=False)
    rows = []
    if body.workspace_shared:
        rows.append(
            DatasetShare(
                workspace_id=user.workspace_id,
                dataset_id=dataset.id,
                target_type="workspace",
                target_id=None,
                role="viewer",
                created_by=user.id,
            )
        )
    rows.extend(
        DatasetShare(
            workspace_id=user.workspace_id,
            dataset_id=dataset.id,
            target_type="user",
            target_id=item.target_id,
            role=item.role,
            created_by=user.id,
        )
        for item in body.users
    )
    rows.extend(
        DatasetShare(
            workspace_id=user.workspace_id,
            dataset_id=dataset.id,
            target_type="team",
            target_id=item.target_id,
            role=item.role,
            created_by=user.id,
        )
        for item in body.teams
    )
    db.add_all(rows)
    activity(
        db,
        user,
        "dataset.shared",
        "dataset",
        dataset.id,
        workspace_shared=body.workspace_shared,
        user_count=len(body.users),
        team_count=len(body.teams),
    )
    db.commit()
    return dataset_shares_response(db, dataset)


@router.post("/api/datasets/{dataset_id}/archive")
def archive_dataset(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "dataset", dataset.id, True)


@router.post("/api/datasets/{dataset_id}/restore")
def restore_dataset(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "dataset", dataset.id, False)


@router.post("/api/tasks/{task_definition_id}/archive")
def archive_task_definition(task_definition_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition:
        raise HTTPException(404, "Task not found")
    require_dataset_access(db, definition.dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "task", definition.id, True)


@router.post("/api/tasks/{task_definition_id}/restore")
def restore_task_definition(task_definition_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition:
        raise HTTPException(404, "Task not found")
    require_dataset_access(db, definition.dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "task", definition.id, False)


@router.get("/api/datasets/{dataset_id}/tasks/{task_definition_id}")
def dataset_task_detail(
    dataset_id: str,
    task_definition_id: str,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    dataset = require_dataset_access(db, dataset_id, user, "viewer", include_archived=include_archived)
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition or definition.dataset_id != dataset.id:
        raise HTTPException(404, "Task not found")
    archived_at = db.scalar(
        select(ObjectArchive.archived_at).where(
            ObjectArchive.object_type == "task", ObjectArchive.object_id == definition.id
        )
    )
    if archived_at and not include_archived:
        raise HTTPException(404, "Task not found")
    current = current_revision(db, definition)
    current_content = (
        task_view(db, current.content, current.id, definition.task_id, current.revision) if current else None
    )
    revisions = db.scalars(
        select(TaskRevision).where(TaskRevision.task_definition_id == definition.id).order_by(TaskRevision.revision)
    ).all()
    memberships = db.scalars(
        select(BatchMember).where(BatchMember.task_definition_id == definition.id).order_by(BatchMember.created_at)
    ).all()
    preload_members(db, memberships)
    batch_ids = {member.batch_id for member in memberships}
    preload_rows(db, Batch, batch_ids)
    failed_by_batch = {}
    if batch_ids:
        failed_by_batch = {
            batch_id: count
            for batch_id, count in db.execute(
                select(BatchMember.batch_id, func.count(BatchMember.id))
                .where(BatchMember.batch_id.in_(batch_ids), BatchMember.status == "failed")
                .group_by(BatchMember.batch_id)
            ).all()
        }
    history = []
    visible_members = []
    for member in memberships:
        batch = db.get(Batch, member.batch_id)
        if not batch or is_archived(db, "run", batch.id) and not include_archived:
            continue
        try:
            get_batch(db, batch.id, user)
        except HTTPException:
            continue
        revision = db.get(TaskRevision, member.task_revision_id)
        reviews = member_reviews(db, member.id)
        jobs = member_jobs(db, member.id)
        latest_review = reviews[-1] if reviews else None
        content = revision.content if revision else {}
        review_summary = review_counts(latest_review.review if latest_review else None)
        review_summary["review_count"] = len(reviews)
        review_summary["review_status"] = "saved" if latest_review else "missing"
        review_summary.update(review_evidence(content, latest_review))
        visible_members.append(member)
        history.append(
            {
                "run_id": batch.id,
                "run_name": batch.name,
                "batch_id": batch.id,
                "created_at": iso(batch.created_at),
                "failed_task_count": int(failed_by_batch.get(batch.id, 0)),
                "member_id": member.id,
                "status": member.status,
                "review_kind": member.review_kind,
                "outcome": (content or {}).get("outcome", "unknown"),
                "score": (content or {}).get("score"),
                "job_id": jobs[0].id if jobs else None,
                "jobs": [job_detail(db, job) for job in jobs],
                "review_summary": review_summary,
                "review_provenance": (
                    copy.deepcopy(latest_review.provenance)
                    if latest_review and isinstance(latest_review.provenance, dict)
                    else None
                ),
                "task_revision_id": member.task_revision_id,
                "task_revision_number": revision.revision if revision else None,
                "reviews": [record(item) for item in reviews],
            }
        )
    return {
        "dataset_id": dataset.id,
        "task_definition": {
            "id": definition.id,
            "task_id": definition.task_id,
            "created_at": iso(definition.created_at),
            "archived_at": iso(archived_at),
        },
        "current_revision": (
            {
                "id": current.id,
                "revision": current.revision,
                "source_revision": current.source_revision,
                "content": current_content,
                "created_at": iso(current.created_at),
            }
            if current
            else None
        ),
        "revisions": [
            {
                "id": rev.id,
                "revision": rev.revision,
                "source_revision": rev.source_revision,
                "created_at": iso(rev.created_at),
            }
            for rev in revisions
        ],
        "summary": dataset_task_summary(db, current.content if current else None, visible_members),
        "runs": history,
    }


@router.get("/api/datasets/{dataset_id}/tasks/{task_definition_id}/export")
def export_dataset_task(
    dataset_id: str,
    task_definition_id: str,
    format: str = Query("json", pattern="^(json|yaml)$"),
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    dataset = require_dataset_access(db, dataset_id, user, include_archived=include_archived)
    definition = db.get(TaskDefinition, task_definition_id)
    if (
        not definition
        or definition.dataset_id != dataset.id
        or (is_archived(db, "task", task_definition_id) and not include_archived)
    ):
        raise HTTPException(404, "Task not found")
    revision = current_revision(db, definition)
    if not revision:
        raise HTTPException(404, "Task revision not found")
    content = task_view(db, revision.content, revision.id, definition.task_id)
    if format == "yaml":
        return PlainTextResponse(
            yaml.safe_dump(content, allow_unicode=True, sort_keys=False), media_type="application/yaml"
        )
    return content


@router.get("/api/datasets/{dataset_id}/sync-preview")
@router.post("/api/datasets/{dataset_id}/sync-preview")
def sync_preview(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    changes = []
    for definition in task_definitions(db, dataset.id):
        current = current_revision(db, definition)
        if current:
            changes.append(
                {
                    "task_id": definition.task_id,
                    "revision_id": current.id,
                    "revision": current.revision,
                    "source_revision": current.source_revision,
                    "content": current.content,
                }
            )
    return {"dataset_id": dataset.id, "new_task_revisions": changes, "count": len(changes)}
