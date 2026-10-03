"""Append-only workspace activity (audit) events."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ActivityEvent, User


def activity(db: Session, user: User | None, action: str, object_type: str, object_id: str | None = None, **details):
    db.add(
        ActivityEvent(
            workspace_id=user.workspace_id if user else details.pop("workspace_id"),
            actor_id=user.id if user else None,
            action=action,
            object_type=object_type,
            object_id=object_id,
            details=details,
        )
    )
