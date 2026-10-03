"""Authorized access to screenshot and review artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_user
from app.core import config
from app.core.database import get_db
from app.core.storage import create_artifact_store
from app.models import BatchMember, Dataset, StoredArtifact, TaskDefinition, TaskRevision, User
from app.services.access import can_view_batch, dataset_role
from app.services.evidence import recorded_image_file

router = APIRouter()


@router.get("/api/artifacts/{task_id}/{relative_path:path}")
def get_artifact(
    task_id: str,
    relative_path: str,
    member_id: str | None = None,
    revision_id: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    norm = Path(relative_path).as_posix()
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts or "\x00" in relative_path:
        raise HTTPException(404, "Artifact not found")
    artifact_query = select(StoredArtifact).where(
        StoredArtifact.relative_path == norm, StoredArtifact.workspace_id == user.workspace_id
    )
    if member_id:
        artifact_query = artifact_query.where(StoredArtifact.member_id == member_id)
    if revision_id:
        artifact_query = artifact_query.where(StoredArtifact.task_revision_id == revision_id)
    artifacts = db.scalars(artifact_query).all()
    if not artifacts:
        raise HTTPException(404, "Artifact not found")
    valid = False
    artifact = None
    for candidate in artifacts:
        allowed = False
        if candidate.member_id:
            member = db.get(BatchMember, candidate.member_id)
            if member and member.task_id == task_id:
                allowed = can_view_batch(db, member.batch_id, user)
        # A member-scoped artifact never falls back to broader dataset authorization.
        if not allowed and candidate.member_id is None and candidate.task_revision_id:
            revision = db.get(TaskRevision, candidate.task_revision_id)
            definition = db.get(TaskDefinition, revision.task_definition_id) if revision else None
            if definition and definition.task_id == task_id:
                dataset = db.get(Dataset, definition.dataset_id)
                allowed = bool(dataset and dataset_role(db, dataset, user))
                if not allowed:
                    refs = db.scalars(select(BatchMember).where(BatchMember.task_revision_id == revision.id)).all()
                    allowed = any(can_view_batch(db, ref.batch_id, user) for ref in refs)
        if allowed:
            artifact, valid = candidate, True
            break
    if not valid:
        raise HTTPException(403, "You do not have access to this evidence")
    if artifact.object_key:
        try:
            body = create_artifact_store(config.settings).get(artifact.object_key)
        except FileNotFoundError:
            raise HTTPException(404, "Recorded artifact is missing") from None
    elif artifact.source_relative_path:
        image = recorded_image_file(artifact.source_relative_path)
        if not image:
            raise HTTPException(404, "Recorded artifact is missing")
        body = image[0]
    else:
        raise HTTPException(404, "Recorded artifact is missing")
    if hashlib.sha256(body).hexdigest() != artifact.sha256:
        raise HTTPException(409, "Recorded artifact checksum mismatch")
    return Response(
        content=body,
        media_type=artifact.media_type,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
