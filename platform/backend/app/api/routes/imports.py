"""JSON and ZIP task imports with validation previews."""

from __future__ import annotations

import copy
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_user, require_role
from app.core import config
from app.core.config import MAX_IMPORT_BYTES
from app.core.database import get_db
from app.core.storage import create_artifact_store
from app.models import StoredArtifact, TaskDefinition, TaskRevision, User, utcnow
from app.schemas import DatasetImport
from app.services.access import require_dataset_access
from app.services.audit import activity
from app.services.evidence import register_evidence
from app.services.records import canonical, digest
from app.services.tasks import current_revision
from app.services.zip_import import IMAGE_TYPES, MAX_ARCHIVE_BYTES, ZipDatasetError, validate_zip_dataset

router = APIRouter()


@router.post("/api/datasets/{dataset_id}/import")
async def import_dataset(
    dataset_id: str,
    body: DatasetImport,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    length = request.headers.get("content-length")
    if length and int(length) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Import exceeds the 32 MB limit")
    if len(canonical(body.model_dump())) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "Import exceeds the 32 MB limit")
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    seen = set()
    created = revised = unchanged = 0
    for content in body.tasks:
        task_id = str(content.get("task_id") or "").strip()
        if not task_id or len(task_id) > 160:
            raise HTTPException(422, "Every task needs a task_id of at most 160 characters")
        if task_id in seen:
            raise HTTPException(422, f"Duplicate task_id in import: {task_id}")
        seen.add(task_id)
        cleaned = copy.deepcopy(content)
        steps = cleaned.get("steps", [])
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise HTTPException(422, f"Task {task_id}: steps must be an array of step records")
        ids = [str(step.get("step_id", "")).strip() for step in steps]
        if any(not step_id for step_id in ids) or len(ids) != len(set(ids)):
            raise HTTPException(422, f"Task {task_id}: step IDs must be present and unique")
        if any(
            not isinstance(step.get("evidence_refs", []), list)
            or any(not isinstance(ref, str) for ref in step.get("evidence_refs", []))
            for step in steps
        ):
            raise HTTPException(422, f"Task {task_id}: evidence_refs must be arrays of strings")
        if any(step.get("screenshot") is not None and not isinstance(step["screenshot"], str) for step in steps):
            raise HTTPException(422, f"Task {task_id}: screenshot paths must be strings")
        if cleaned.get("review") is not None and (
            not isinstance(cleaned["review"], dict)
            or not isinstance(cleaned["review"].get("steps", []), list)
            or any(not isinstance(step, dict) for step in cleaned["review"].get("steps", []))
        ):
            raise HTTPException(422, f"Task {task_id}: review must contain an array of step records")
        fingerprint = digest(cleaned)
        definition = db.scalar(
            select(TaskDefinition).where(TaskDefinition.dataset_id == dataset.id, TaskDefinition.task_id == task_id)
        )
        if not definition:
            definition = TaskDefinition(dataset_id=dataset.id, task_id=task_id)
            db.add(definition)
            db.flush()
            revision_number = 1
            created += 1
        else:
            current = current_revision(db, definition)
            if current and current.source_revision == fingerprint:
                unchanged += 1
                continue
            revision_number = (current.revision + 1) if current else 1
            revised += 1
        revision = TaskRevision(
            task_definition_id=definition.id, revision=revision_number, source_revision=fingerprint, content=cleaned
        )
        db.add(revision)
        db.flush()
        definition.current_revision_id = revision.id
        register_evidence(db, user, revision, None, cleaned)
    dataset.updated_at = utcnow()
    activity(db, user, "dataset.imported", "dataset", dataset.id, created=created, revised=revised, unchanged=unchanged)
    db.commit()
    return {
        "dataset_id": dataset.id,
        "created": created,
        "revised": revised,
        "unchanged": unchanged,
        "imported": created + revised + unchanged,
        "task_count": len(seen),
    }


async def _read_zip_request(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/zip":
        raise ZipDatasetError(
            [
                {
                    "path": "request",
                    "message": "Send the ZIP as raw application/zip bytes",
                    "code": "unsupported_media_type",
                }
            ]
        )
    length = request.headers.get("content-length")
    if length:
        try:
            declared_size = int(length)
        except ValueError:
            raise ZipDatasetError(
                [{"path": "request", "message": "Invalid Content-Length header", "code": "invalid_content_length"}]
            ) from None
        if declared_size > MAX_ARCHIVE_BYTES:
            raise ZipDatasetError(
                [{"path": "archive", "message": "ZIP archive exceeds the 32 MB limit", "code": "archive_too_large"}]
            )
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_ARCHIVE_BYTES:
            raise ZipDatasetError(
                [{"path": "archive", "message": "ZIP archive exceeds the 32 MB limit", "code": "archive_too_large"}]
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _zip_validation_http_error(exc: ZipDatasetError):
    return HTTPException(
        status_code=422, detail={"message": "ZIP dataset is invalid", "errors": exc.errors, "warnings": exc.warnings}
    )


@router.post("/api/imports/zip/validate")
async def validate_dataset_zip(request: Request, user: User = Depends(require_role("admin", "manager"))):
    try:
        payload = await _read_zip_request(request)
        validated = validate_zip_dataset(payload)
    except ZipDatasetError as exc:
        raise _zip_validation_http_error(exc) from None
    return {
        "valid": True,
        "task_count": len(validated.tasks),
        "screenshot_count": len(set(path for paths in validated.assets_by_task.values() for path in paths)),
        "tasks": validated.summaries,
        "warnings": validated.warnings,
    }


@router.post("/api/datasets/{dataset_id}/import-zip")
async def import_dataset_zip(
    dataset_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(get_user)
):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    try:
        payload = await _read_zip_request(request)
        validated = validate_zip_dataset(payload)
    except ZipDatasetError as exc:
        raise _zip_validation_http_error(exc) from None

    created = revised = unchanged = 0
    planned = []
    try:
        for content in validated.tasks:
            task_id = content["task_id"]
            asset_paths = validated.assets_by_task.get(task_id, [])
            asset_hashes = {path: hashlib.sha256(validated.assets[path]).hexdigest() for path in asset_paths}
            fingerprint = digest({"task": content, "assets": asset_hashes})
            definition = db.scalar(
                select(TaskDefinition).where(TaskDefinition.dataset_id == dataset.id, TaskDefinition.task_id == task_id)
            )
            if not definition:
                definition = TaskDefinition(dataset_id=dataset.id, task_id=task_id)
                db.add(definition)
                db.flush()
                revision_number = 1
                created += 1
            else:
                current = current_revision(db, definition)
                if current and current.source_revision == fingerprint:
                    unchanged += 1
                    continue
                revision_number = (current.revision + 1) if current else 1
                revised += 1
            revision = TaskRevision(
                task_definition_id=definition.id, revision=revision_number, source_revision=fingerprint, content=content
            )
            db.add(revision)
            db.flush()
            definition.current_revision_id = revision.id
            planned.append((task_id, revision, asset_paths))

        if planned:
            store = create_artifact_store(config.settings)
            for _task_id, revision, asset_paths in planned:
                for relative_path in asset_paths:
                    image = validated.assets[relative_path]
                    sha = hashlib.sha256(image).hexdigest()
                    suffix = "." + relative_path.rsplit(".", 1)[-1].lower()
                    key = (
                        f"workspaces/{dataset.workspace_id}/datasets/{dataset.id}/"
                        f"task-revisions/{revision.id}/assets/{sha}{suffix}"
                    )
                    object_key = store.put(key, image, IMAGE_TYPES[suffix])
                    db.add(
                        StoredArtifact(
                            workspace_id=dataset.workspace_id,
                            task_revision_id=revision.id,
                            relative_path=relative_path,
                            media_type=IMAGE_TYPES[suffix],
                            object_key=object_key,
                            sha256=sha,
                        )
                    )
        dataset.updated_at = utcnow()
        activity(
            db,
            user,
            "dataset.imported_zip",
            "dataset",
            dataset.id,
            created=created,
            revised=revised,
            unchanged=unchanged,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Dataset changed during ZIP import; refresh and retry") from None
    except Exception:
        db.rollback()
        raise HTTPException(503, "ZIP import failed before database commit; no task revisions were committed") from None
    return {
        "dataset_id": dataset.id,
        "created": created,
        "revised": revised,
        "unchanged": unchanged,
        "imported": created + revised + unchanged,
        "task_count": len(validated.tasks),
        "warnings": validated.warnings,
    }
