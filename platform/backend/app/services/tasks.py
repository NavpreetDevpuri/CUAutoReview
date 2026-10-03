"""Task definition and current-revision lookups."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import TaskDefinition, TaskRevision


def task_definitions(db: Session, dataset_id: str) -> list[TaskDefinition]:
    return db.scalars(
        select(TaskDefinition).where(TaskDefinition.dataset_id == dataset_id).order_by(TaskDefinition.task_id)
    ).all()


def current_revision(db: Session, definition: TaskDefinition) -> TaskRevision | None:
    return db.get(TaskRevision, definition.current_revision_id) if definition.current_revision_id else None
