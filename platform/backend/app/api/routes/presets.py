"""Prompt workflows, saved execution presets and provider model catalogs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_user, require_role
from app.core.database import get_db
from app.models import Preset, PresetRevision, ProviderModelCatalog, User, utcnow
from app.schemas import PresetCreate, ProviderModelCatalogSync
from app.services.audit import activity
from app.services.execution import validate_execution, workflow_catalog
from app.services.records import digest, iso, record

router = APIRouter()


@router.get("/api/workflows")
def workflows(user: User = Depends(get_user)):
    return {"items": workflow_catalog()}


@router.get("/api/presets")
def presets(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    query = select(Preset).where(Preset.workspace_id == user.workspace_id, ~Preset.name.like("__run_config__%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    size = min(per_page, 200)
    items = db.scalars(query.order_by(Preset.name).offset((page - 1) * size).limit(size)).all()
    output = []
    for p in items:
        entry = record(p)
        revisions = db.scalars(
            select(PresetRevision).where(PresetRevision.preset_id == p.id).order_by(PresetRevision.revision)
        ).all()
        entry["revisions"] = [
            record(r, omit=("configuration",)) | {"configuration": r.configuration, "preset_id": p.id}
            for r in revisions
        ]
        entry["latest_revision"] = entry["revisions"][-1] if entry["revisions"] else None
        if entry["latest_revision"]:
            entry.update(entry["latest_revision"])
            entry["id"] = p.id
            entry["name"] = p.name
        output.append(entry)
    return {"items": output, "total": total}


@router.post("/api/presets")
def create_preset(
    body: PresetCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))
):
    if body.name.strip().startswith("__run_config__"):
        raise HTTPException(422, "Preset name uses a reserved prefix")
    model = body.model or ("retained-poc" if body.backend == "saved_replay" else None)
    if not model:
        raise HTTPException(422, "A model is required for this backend")
    if body.backend == "saved_replay" and model != "retained-poc":
        # Model is informational for saved fixtures; avoid accidental representation as live inference.
        raise HTTPException(422, "saved_replay must use model 'retained-poc'")
    if body.backend != "saved_replay" and body.budget_usd is None:
        raise HTTPException(422, "Explicit non-replay presets need a pinned budget")
    # Presets prefill new runs, so they must satisfy the same bounds and never store credentials.
    validate_execution({**body.model_dump(), "model": model})
    preset = db.scalar(select(Preset).where(Preset.workspace_id == user.workspace_id, Preset.name == body.name.strip()))
    if not preset:
        preset = Preset(workspace_id=user.workspace_id, name=body.name.strip(), created_by=user.id)
        db.add(preset)
        db.flush()
        revision_number = 1
    else:
        revision_number = (
            db.scalar(select(func.max(PresetRevision.revision)).where(PresetRevision.preset_id == preset.id)) or 0
        ) + 1
    revision = PresetRevision(
        preset_id=preset.id,
        revision=revision_number,
        backend=body.backend,
        model=model,
        reasoning=body.reasoning,
        budget_usd=body.budget_usd,
        configuration=body.configuration,
        config_hash=digest(body.model_dump()),
        created_by=user.id,
    )
    db.add(revision)
    activity(db, user, "preset.revision_created", "preset", preset.id, backend=body.backend, revision=revision_number)
    db.commit()
    return {
        **record(preset),
        **record(revision),
        "preset_id": preset.id,
        "id": preset.id,
        "name": preset.name,
        "revisions": [record(revision)],
    }


@router.get("/api/providers")
def providers(user: User = Depends(get_user)):
    try:
        from app.worker.review_backends import provider_capabilities

        values = provider_capabilities()
    except Exception:
        values = [
            {
                "id": "saved_replay",
                "name": "Saved POC replay",
                "available": True,
                "configured": True,
                "capabilities": ["saved_result"],
            }
        ]
    values = [
        {
            **item,
            "supported": bool(
                item.get("execution_enabled", item.get("available"))
                and item.get("id") in ("saved_replay", "model_api", "litellm", "claude_code", "codex", "gemini_cli")
            ),
        }
        for item in values
    ]
    if not any(item.get("id") == "litellm" for item in values):
        api = next((item for item in values if item.get("id") == "model_api"), None)
        if api:
            values.append({**api, "id": "litellm", "name": "LiteLLM API (alias)"})
    return {"default_backend": "saved_replay", "items": values, "backends": values, "providers": values}


PROVIDER_MODEL_BACKENDS = ("model_api", "litellm", "codex", "gemini_cli", "claude_code")


PROVIDER_MODEL_BACKEND_PATTERN = "^({})$".format("|".join(PROVIDER_MODEL_BACKENDS))


def provider_model_payload(snapshot: ProviderModelCatalog | None, backend: str) -> dict[str, Any]:
    if snapshot is None:
        return {
            "backend": backend,
            "models": [],
            "source": "not_discovered",
            "fetched_at": None,
            "status": "unknown",
            "note": "Provider model availability has not been checked.",
        }
    return {
        "backend": snapshot.backend,
        "models": snapshot.models or [],
        "source": snapshot.source,
        "fetched_at": iso(snapshot.fetched_at),
        "status": snapshot.status,
        "note": snapshot.note,
    }


def validate_provider_model_ids(catalog: ProviderModelCatalogSync) -> None:
    if catalog.status == "available" and not catalog.models:
        raise HTTPException(422, "An available provider catalog must contain at least one model")
    identifiers = [item.id for item in catalog.models]
    if len(set(identifiers)) != len(identifiers):
        raise HTTPException(422, "Provider model IDs must be unique")
    for item in catalog.models:
        if catalog.backend == "gemini_cli":
            valid = item.provider == "google" and item.id.startswith("gemini-")
        elif catalog.backend == "codex":
            valid = item.provider == "openai" and (
                item.id.startswith("gpt-") or (len(item.id) > 1 and item.id[0] == "o" and item.id[1].isdigit())
            )
        elif catalog.backend == "claude_code":
            valid = item.provider == "anthropic" and item.id.startswith("claude-")
        elif item.provider == "google":
            valid = item.id.startswith("gemini/gemini-")
        elif item.provider == "openai":
            valid = item.id.startswith("openai/gpt-") or item.id.startswith("openai/o")
        else:
            valid = item.id.startswith("anthropic/claude-")
        if not valid:
            raise HTTPException(422, f"Model ID is not valid for provider backend '{catalog.backend}'")


@router.get("/api/providers/models")
def provider_models(
    backend: str = Query(..., pattern=PROVIDER_MODEL_BACKEND_PATTERN),
    db: Session = Depends(get_db),
    user: User = Depends(get_user),
):
    snapshot = db.get(ProviderModelCatalog, (user.workspace_id, backend))
    return provider_model_payload(snapshot, backend)


@router.post("/api/providers/models/sync")
def sync_provider_models(
    body: ProviderModelCatalogSync, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))
):
    """Store a safe metadata snapshot submitted by a credential-owning runner; never calls providers."""
    validate_provider_model_ids(body)
    snapshot = db.get(ProviderModelCatalog, (user.workspace_id, body.backend))
    if snapshot is None:
        snapshot = ProviderModelCatalog(workspace_id=user.workspace_id, backend=body.backend)
        db.add(snapshot)
    snapshot.status = body.status
    snapshot.source = body.source
    snapshot.fetched_at = body.fetched_at
    snapshot.models = [item.model_dump(exclude_none=True) for item in body.models]
    snapshot.note = None
    snapshot.updated_at = utcnow()
    db.commit()
    return provider_model_payload(snapshot, body.backend)
