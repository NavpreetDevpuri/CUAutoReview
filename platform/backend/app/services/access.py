"""Access control: workspace roles, dataset shares, run grants, visibility and archive state."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, Dataset, ObjectArchive, User, utcnow
from app.services.audit import activity
from app.services.read_cache import (
    archived_objects,
    batch_grants,
    dataset_shares,
    preload_rows,
    run_source_ids,
    user_team_ids,
)

ROLE_ORDER = {"viewer": 0, "reviewer": 1, "manager": 2, "admin": 3}


def get_batch(db: Session, batch_id: str, user: User, *, required_role: str = "viewer") -> tuple[Batch, str]:
    batch = db.get(Batch, batch_id)
    if not batch or batch.workspace_id != user.workspace_id:
        raise HTTPException(404, "Batch not found")
    effective = user.role if user.role in ("admin", "manager") else None
    source_dataset_ids = set(run_source_ids(db, batch)) or {batch.dataset_id}
    shared_roles = []
    for source_id in source_dataset_ids:
        source_dataset = db.get(Dataset, source_id)
        if source_dataset:
            shared_role = dataset_role(db, source_dataset, user)
            if shared_role:
                shared_roles.append(shared_role)
    # A dataset share reaches a multi-source run only when every source is shared;
    # direct batch grants remain an explicit run-wide authorization.
    if len(shared_roles) == len(source_dataset_ids) and shared_roles:
        shared_role = min(shared_roles, key=lambda role: ROLE_ORDER.get(role, -1))
        if effective is None or ROLE_ORDER.get(shared_role, -1) > ROLE_ORDER.get(effective, -1):
            effective = shared_role
    grants = batch_grants(db, batch)
    team_ids = user_team_ids(db, user.id)
    for grant in grants:
        grants_user = grant.user_id == user.id or (grant.team_id and grant.team_id in team_ids)
        if grants_user and (effective is None or ROLE_ORDER.get(grant.role, -1) > ROLE_ORDER.get(effective, -1)):
            effective = grant.role
    if effective is None or ROLE_ORDER.get(effective, -1) < ROLE_ORDER.get(required_role, 0):
        raise HTTPException(403, "You do not have access to this batch")
    return batch, effective


def need_batch_manager(role: str):
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["manager"]:
        raise HTTPException(403, "Batch manager access required")


def dataset_role(db: Session, dataset: Dataset, user: User) -> str | None:
    if dataset.workspace_id != user.workspace_id:
        return None
    if user.role in ("admin", "manager"):
        return user.role
    shares = dataset_shares(db, user.workspace_id, dataset.id)
    team_ids = user_team_ids(db, user.id)
    roles = []
    for share in shares:
        if (
            (share.target_type == "workspace" and share.target_id is None)
            or (share.target_type == "user" and share.target_id == user.id)
            or (share.target_type == "team" and share.target_id in team_ids)
        ):
            roles.append(share.role)
    return max(roles, key=lambda role: ROLE_ORDER.get(role, -1)) if roles else None


def require_dataset_access(
    db: Session, dataset_id: str, user: User, role: str = "viewer", *, include_archived: bool = False
) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if not dataset or dataset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Dataset not found")
    if not include_archived and is_archived(db, "dataset", dataset.id):
        raise HTTPException(404, "Dataset not found")
    actual = dataset_role(db, dataset, user)
    if actual is None or ROLE_ORDER.get(actual, -1) < ROLE_ORDER[role]:
        raise HTTPException(403, "You do not have access to this dataset")
    return dataset


def is_archived(db: Session, object_type: str, object_id: str) -> bool:
    return object_id in archived_objects(db, object_type)


def set_archived(db: Session, user: User, object_type: str, object_id: str, archived: bool) -> dict[str, Any]:
    row = db.scalar(
        select(ObjectArchive).where(ObjectArchive.object_type == object_type, ObjectArchive.object_id == object_id)
    )
    if not row:
        row = ObjectArchive(workspace_id=user.workspace_id, object_type=object_type, object_id=object_id)
        db.add(row)
    if archived:
        if row.archived_at is None:
            row.archived_at, row.archived_by = utcnow(), user.id
        row.restored_at = None
    else:
        row.archived_at, row.archived_by, row.restored_at = None, None, utcnow()
    activity(db, user, f"{object_type}.{'archived' if archived else 'restored'}", object_type, object_id)
    db.commit()
    return {"archived": archived, "object_type": object_type, "object_id": object_id}


def visible_batches(db: Session, user: User, include_archived: bool = False) -> list[Batch]:
    rows = db.scalars(
        select(Batch).where(Batch.workspace_id == user.workspace_id).order_by(Batch.created_at.desc())
    ).all()
    preload_rows(
        db, Dataset, {source_id for batch in rows for source_id in (run_source_ids(db, batch) or [batch.dataset_id])}
    )
    output = []
    for batch in rows:
        if not include_archived and is_archived(db, "run", batch.id):
            continue
        try:
            get_batch(db, batch.id, user)
            output.append(batch)
        except HTTPException:
            continue
    return output


def can_view_batch(db: Session, batch_id: str, user: User) -> bool:
    try:
        get_batch(db, batch_id, user)
        return True
    except HTTPException:
        return False


def visible_batch_ids(db: Session, user: User) -> set[str]:
    """Return runs the user can read, including archived ones, by the same rules as get_batch.

    Direct and team grants and dataset shares all count, so job lists and the
    overview match what the run pages already show.
    """
    return {batch.id for batch in visible_batches(db, user, include_archived=True)}
