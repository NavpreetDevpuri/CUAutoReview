"""Serialization and content-hashing helpers shared by routes and services."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def record(obj: Any, *, omit: tuple[str, ...] = ()) -> dict[str, Any]:
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in omit}
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            data[key] = iso(value)
    return data


def list_page(db: Session, model: Any, workspace_id: str, page: int, per_page: int):
    query = select(model).where(model.workspace_id == workspace_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(model.created_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return {"items": [record(item) for item in items], "total": total}


def me_record(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "workspace_id": user.workspace_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "active": user.active,
    }
