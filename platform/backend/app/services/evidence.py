"""Bundled POC screenshot evidence: path validation and registration as stored artifacts."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import config
from app.models import BatchMember, StoredArtifact, TaskRevision, User
from app.services.zip_import import image_content_type


def recorded_source_file(relative: str) -> Path | None:
    """Resolve only controlled local fixture paths, never user paths or URLs."""
    if not isinstance(relative, str) or not relative or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", relative):
        return None
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    if raw.parts and raw.parts[0] == "poc":
        candidate = config.PROJECT_ROOT / raw
    else:
        candidate = config.PROJECT_ROOT / "poc" / raw
    try:
        resolved = candidate.resolve(strict=True)
        root = (config.PROJECT_ROOT / "poc").resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    except (OSError, RuntimeError):
        return None
    return None


def recorded_image_file(relative: str) -> tuple[bytes, str] | None:
    """Bundled POC screenshots only: PNG/JPEG/WebP under poc/data whose bytes match the extension."""
    path = recorded_source_file(relative)
    if not path or not path.is_relative_to((config.PROJECT_ROOT / "poc" / "data").resolve()):
        return None
    body = path.read_bytes()
    media_type = image_content_type(path.name, body)
    return (body, media_type) if media_type else None


def register_evidence(
    db: Session, user: User, task_revision: TaskRevision, member: BatchMember | None, content: dict[str, Any]
):
    existing = set()
    if member:
        existing = set(
            db.scalars(select(StoredArtifact.relative_path).where(StoredArtifact.member_id == member.id)).all()
        )
    steps = content.get("steps") or []
    for step in steps:
        relative = step.get("screenshot")
        image = recorded_image_file(relative) if relative else None
        if not image:
            continue
        normalized = Path(relative).as_posix()
        if normalized in existing:
            continue
        body, media_type = image
        db.add(
            StoredArtifact(
                workspace_id=user.workspace_id,
                task_revision_id=task_revision.id,
                member_id=member.id if member else None,
                relative_path=normalized,
                media_type=media_type,
                source_relative_path=normalized if normalized.startswith("poc/") else f"poc/{normalized}",
                sha256=hashlib.sha256(body).hexdigest(),
            )
        )
