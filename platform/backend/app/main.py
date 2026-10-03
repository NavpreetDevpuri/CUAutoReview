"""Local CU AutoReview API. All write workflows are server-authorized and auditable."""
from __future__ import annotations

import copy
import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.responses import FileResponse
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from .config import PROJECT_ROOT, settings
from .database import init_db, make_engine, make_session_factory, session_dependency
from .models import (
    ActivityEvent, Batch, BatchGrant, BatchMember, CandidateDecision,
    Dataset, DatasetShare, Job, JobAttempt, ObjectArchive, OutboxEvent, Preset, PresetRevision,
    ProviderModelCatalog, ProposalFeedback, ProposalRevision, ReviewResult, Session as LoginSession,
    RunConfiguration, RunSource, StoredArtifact, SyncWave, TaskDefinition, TaskFeedback, TaskRevision,
    TaxonomyCandidate, TaxonomyProposal, TaxonomyRelease, Team, TeamMember,
    User, Workspace, as_utc, uid, utcnow,
)
from .schemas import (
    AddTeamMember, AnalyticsCompare, AnalyticsQuery, BatchCreate, BatchGrantCreate, CandidateApproval,
    CandidateRejection, DatasetCreate, DatasetImport, DatasetSharesUpdate, DatasetUpdate,
    FeedbackCreate, Login, PresetCreate, ProposalFeedback as ProposalFeedbackIn,
    ProviderModelCatalogSync, RunConfigure, RunCreate, RunExecution, RunRerun, Signup, StartBatch,
    TaxonomyConsolidate, TaxonomyProposalCreate, TeamCreate, TeamUpdate, UserUpdate,
)
from .security import hash_password, new_session_token, token_digest, verify_password
from .storage import create_artifact_store
from .taxonomy_lock import lock_taxonomy_workspace
from .zip_import import IMAGE_TYPES, MAX_ARCHIVE_BYTES, ZipDatasetError, copy_revision_artifacts_to_member, validate_zip_dataset


engine = make_engine(settings.database_url)
SessionLocal = make_session_factory(engine)
get_db = session_dependency(SessionLocal)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    try:
        yield
    finally:
        await shutdown()


app = FastAPI(title="CU AutoReview local API", version="1.0.0", lifespan=lifespan)
ROLE_ORDER = {"viewer": 0, "reviewer": 1, "manager": 2, "admin": 3}
MAX_IMPORT_BYTES = 32 * 1024 * 1024
_signup_lock = threading.Lock()
logger = logging.getLogger("cuautoreview.queue")


@app.middleware("http")
async def same_origin_cookie_writes(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                host = request.headers.get("host", "")
                if parsed.scheme != request.url.scheme or parsed.netloc.lower() != host.lower() or parsed.path or parsed.query or parsed.fragment:
                    return Response(status_code=403, content=json.dumps({"detail": "Cross-origin mutation denied"}),
                                    media_type="application/json")
            except ValueError:
                return Response(status_code=403, content=json.dumps({"detail": "Invalid request origin"}),
                                media_type="application/json")
        elif request.cookies.get(settings.session_cookie):
            # Browser fetch sends Origin for unsafe methods. Cookie-authenticated requests without it
            # are rejected unless same-origin Fetch Metadata is explicitly supplied.
            if request.headers.get("sec-fetch-site") != "same-origin":
                return Response(status_code=403, content=json.dumps({"detail": "Origin required for cookie-authenticated mutation"}),
                                media_type="application/json")
    return await call_next(request)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def workflow_catalog() -> list[dict[str, Any]]:
    return [{
        "id": "trajectory_review", "revision_id": "trajectory_review@1", "name": "Trajectory review",
        "version": 1, "description": "Evidence-grounded review of failures and recovery in computer-use trajectories.",
        "input_contract": "A task instruction, recorded outcome, ordered steps, evidence references, and authorized screenshots.",
        "output_schema_version": "1",
        "supported_backends": ["saved_replay", "model_api", "litellm", "claude_code", "codex", "gemini_cli"],
        "stages": [
            {"id": "failure_analysis", "name": "Failure analysis", "kind": "failure_analysis",
             "prompt": "Explain evidence-supported mistakes that contributed to the recorded failed outcome and any later recovery. Separate recovery from outcome contribution; do not invent unseen intent or effects."},
            {"id": "pass_recovery", "name": "Pass recovery", "kind": "pass_recovery",
             "prompt": "The recorded task passed. Find intermediate mistakes and subsequent recovery when supported. Passing does not prove an error-free path; outcome contribution must be not_applicable."},
        ],
    }]


def workflow_by_revision(revision_id: str) -> dict[str, Any]:
    for item in workflow_catalog():
        if revision_id in (item["revision_id"], item["id"]):
            return item
    raise HTTPException(404, "Workflow revision not found")


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


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


def activity(db: Session, user: User | None, action: str, object_type: str, object_id: str | None = None, **details):
    db.add(ActivityEvent(workspace_id=user.workspace_id if user else details.pop("workspace_id"),
                         actor_id=user.id if user else None, action=action, object_type=object_type,
                         object_id=object_id, details=details))


def get_user(request: Request, db: Session = Depends(get_db)) -> User:
    raw = request.cookies.get(settings.session_cookie)
    if not raw:
        raise HTTPException(401, "Sign in required")
    session = db.get(LoginSession, token_digest(raw))
    if not session or as_utc(session.expires_at) <= utcnow():
        raise HTTPException(401, "Session expired")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Account inactive")
    return user


def signup_transaction_lock(db: Session = Depends(get_db)):
    """Serialize local signup and hold a cross-process PostgreSQL bootstrap lock."""
    _signup_lock.acquire()
    try:
        if db.bind and db.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            db.execute(text("SELECT pg_advisory_xact_lock(53325899261001)"))
        yield
    finally:
        _signup_lock.release()


def require_role(*roles: str):
    def dependency(user: User = Depends(get_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "This action requires " + " or ".join(roles) + " access")
        return user
    return dependency


def get_batch(db: Session, batch_id: str, user: User, *, required_role: str = "viewer") -> tuple[Batch, str]:
    batch = db.get(Batch, batch_id)
    if not batch or batch.workspace_id != user.workspace_id:
        raise HTTPException(404, "Batch not found")
    effective = user.role if user.role in ("admin", "manager") else None
    source_dataset_ids = set(db.scalars(select(RunSource.dataset_id).where(RunSource.batch_id == batch.id)).all()) or {batch.dataset_id}
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
    grants = db.scalars(select(BatchGrant).where(BatchGrant.batch_id == batch.id)).all()
    team_ids = set(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user.id)).all())
    for grant in grants:
        if grant.user_id == user.id or (grant.team_id and grant.team_id in team_ids):
            if effective is None or ROLE_ORDER.get(grant.role, -1) > ROLE_ORDER.get(effective, -1):
                effective = grant.role
    if effective is None or ROLE_ORDER.get(effective, -1) < ROLE_ORDER.get(required_role, 0):
        raise HTTPException(403, "You do not have access to this batch")
    return batch, effective


def require_batch(required_role: str = "viewer"):
    def dependency(batch_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)) -> tuple[Batch, User, str]:
        batch, role = get_batch(db, batch_id, user, required_role=required_role)
        return batch, user, role
    return dependency


def need_batch_manager(role: str):
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER["manager"]:
        raise HTTPException(403, "Batch manager access required")


def dataset_role(db: Session, dataset: Dataset, user: User) -> str | None:
    if dataset.workspace_id != user.workspace_id:
        return None
    if user.role in ("admin", "manager"):
        return user.role
    shares = db.scalars(select(DatasetShare).where(DatasetShare.dataset_id == dataset.id,
        DatasetShare.workspace_id == user.workspace_id)).all()
    team_ids = set(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user.id)).all())
    roles = []
    for share in shares:
        if ((share.target_type == "workspace" and share.target_id is None) or
            (share.target_type == "user" and share.target_id == user.id) or
            (share.target_type == "team" and share.target_id in team_ids)):
            roles.append(share.role)
    return max(roles, key=lambda role: ROLE_ORDER.get(role, -1)) if roles else None


def require_dataset_access(db: Session, dataset_id: str, user: User, role: str = "viewer",
                           *, include_archived: bool = False) -> Dataset:
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
    return bool(db.scalar(select(ObjectArchive.id).where(ObjectArchive.object_type == object_type,
        ObjectArchive.object_id == object_id, ObjectArchive.archived_at.is_not(None))))


def set_archived(db: Session, user: User, object_type: str, object_id: str, archived: bool) -> dict[str, Any]:
    row = db.scalar(select(ObjectArchive).where(ObjectArchive.object_type == object_type,
        ObjectArchive.object_id == object_id))
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


def task_definitions(db: Session, dataset_id: str) -> list[TaskDefinition]:
    return db.scalars(select(TaskDefinition).where(TaskDefinition.dataset_id == dataset_id).order_by(TaskDefinition.task_id)).all()


def current_revision(db: Session, definition: TaskDefinition) -> TaskRevision | None:
    return db.get(TaskRevision, definition.current_revision_id) if definition.current_revision_id else None


def _recorded_source_file(relative: str) -> Path | None:
    """Resolve only controlled local fixture paths, never user paths or URLs."""
    if not isinstance(relative, str) or not relative or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", relative):
        return None
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    if raw.parts and raw.parts[0] == "poc":
        candidate = PROJECT_ROOT / raw
    else:
        candidate = PROJECT_ROOT / "poc" / raw
    try:
        resolved = candidate.resolve(strict=True)
        root = (PROJECT_ROOT / "poc").resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    except (OSError, RuntimeError):
        return None
    return None


def register_evidence(db: Session, user: User, task_revision: TaskRevision, member: BatchMember | None,
                      content: dict[str, Any]):
    existing = set()
    if member:
        existing = set(db.scalars(select(StoredArtifact.relative_path).where(StoredArtifact.member_id == member.id)).all())
    steps = content.get("steps") or []
    for step in steps:
        relative = step.get("screenshot")
        path = _recorded_source_file(relative) if relative else None
        if not path:
            continue
        normalized = Path(relative).as_posix()
        if normalized in existing:
            continue
        db.add(StoredArtifact(workspace_id=user.workspace_id, task_revision_id=task_revision.id,
                              member_id=member.id if member else None, relative_path=normalized,
                              media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                              source_relative_path=normalized if normalized.startswith("poc/") else f"poc/{normalized}",
                              sha256=hashlib.sha256(path.read_bytes()).hexdigest()))


def task_view(db: Session, content: dict[str, Any], revision_id: str, task_id: str,
              revision_number: int | None = None,
              member: BatchMember | None = None, review_result: ReviewResult | None = None):
    output = copy.deepcopy(content)
    output["task_id"] = task_id
    output["revision_id"] = revision_id
    task_revision = db.get(TaskRevision, revision_id)
    definition = db.get(TaskDefinition, task_revision.task_definition_id) if task_revision else None
    output["task_definition_id"] = definition.id if definition else None
    output["dataset_id"] = definition.dataset_id if definition else None
    if revision_number is not None:
        output["revision"] = revision_number
    output["status"] = member.status if member else "not_in_batch"
    output["processing_status"] = output["status"]
    output["member_id"] = member.id if member else None
    review = review_result.review if review_result else (content.get("review") if member is None else None)
    output["review"] = copy.deepcopy(review) if review is not None else None
    output["review_provenance"] = (copy.deepcopy(review_result.provenance)
                                   if review_result and isinstance(review_result.provenance, dict) else None)
    if member and content.get("review") is not None:
        output["source_review"] = copy.deepcopy(content["review"])
    output["review_kind"] = review_result.review_kind if review_result else (review or {}).get("review_kind")
    output["review_history"] = []
    if member:
        history = db.scalars(select(ReviewResult).where(ReviewResult.member_id == member.id).order_by(ReviewResult.revision)).all()
        output["review_history"] = [record(item) for item in history]
        jobs = db.scalars(select(Job).where(Job.member_id == member.id).order_by(Job.created_at)).all()
        output["jobs"] = [job_detail(db, job) for job in jobs]
        output["job_id"] = jobs[0].id if jobs else None
        artifact_rows = db.scalars(select(StoredArtifact).where(StoredArtifact.member_id == member.id)).all()
    else:
        output["jobs"] = []
        output["job_id"] = None
        artifact_rows = db.scalars(select(StoredArtifact).where(StoredArtifact.task_revision_id == revision_id)).all()
    artifact_by_path = {a.relative_path: a for a in artifact_rows}
    step_annotations = {str(s.get("step_id")): s for s in (review or {}).get("steps", [])}
    for step in output.get("steps") or []:
        # Computed links must come from authorized artifact rows, never imported URLs.
        step.pop("screenshot_url", None)
        step_id = str(step.get("step_id"))
        annotation = step_annotations.get(step_id) or {}
        # Keep all original source fields; add only exact recorded review links.
        if "episode_refs" in annotation:
            step["episode_refs"] = copy.deepcopy(annotation["episode_refs"])
        rel = step.get("screenshot")
        artifact = artifact_by_path.get(Path(rel).as_posix()) if isinstance(rel, str) else None
        if artifact:
            suffix = (f"?member_id={quote(member.id, safe='')}" if member else
                      f"?revision_id={quote(revision_id, safe='')}" if revision_id else "")
            step["screenshot_url"] = f"/api/artifacts/{quote(task_id, safe='')}/{quote(artifact.relative_path, safe='/')}{suffix}"
            step["artifact_status"] = "recorded"
        elif rel:
            step["artifact_status"] = "missing"
    artifact_suffix = (f"?member_id={quote(member.id, safe='')}" if member else
                       f"?revision_id={quote(revision_id, safe='')}" if revision_id else "")
    output["artifacts"] = [record(a) | {"url": f"/api/artifacts/{quote(task_id, safe='')}/{quote(a.relative_path, safe='/')}{artifact_suffix}"}
                            for a in artifact_rows]
    output["raw_url"] = (f"/api/batches/{member.batch_id}/tasks/{quote(task_id, safe='')}/export?format=json&member_id={quote(member.id, safe='')}"
                         if member else None)
    return output


def member_review(db: Session, member: BatchMember) -> ReviewResult | None:
    return db.scalar(select(ReviewResult).where(ReviewResult.member_id == member.id).order_by(ReviewResult.revision.desc()).limit(1))


def job_detail(db: Session, job: Job) -> dict[str, Any]:
    item = record(job)
    preset = db.get(PresetRevision, job.preset_revision_id)
    item["backend"] = preset.backend if preset else None
    item["model"] = preset.model if preset else None
    item["budget_usd"] = preset.budget_usd if preset else None
    item["max_total_budget_usd"] = (float(preset.budget_usd) * job.max_attempts
                                    if preset and preset.budget_usd is not None else None)
    attempts = db.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id)
                          .order_by(JobAttempt.attempt_number)).all()
    item["attempts"] = [record(attempt) for attempt in attempts]
    known_attempt_costs = [float(attempt.cost_usd) for attempt in attempts if attempt.cost_usd is not None]
    item["cumulative_cost_usd"] = sum(known_attempt_costs) if known_attempt_costs else None
    item["unknown_cost_attempts"] = sum(attempt.cost_usd is None for attempt in attempts)
    item["retry_eligible"] = (job.status in ("failed", "completed") and
                              job.attempt_count < job.max_attempts)
    return item


def _review_counts(review: dict | None) -> dict[str, Any]:
    episodes = review.get("episodes") if isinstance(review, dict) else None
    episodes = episodes if isinstance(episodes, list) else []
    labels: dict[tuple[str, str], int] = {}
    flagged_steps: set[str] = set()
    recovery_step_count = 0
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        label_id = str(episode.get("label_id") or "unlabeled")
        label_name = str(episode.get("label_name") or label_id)
        labels[(label_id, label_name)] = labels.get((label_id, label_name), 0) + 1
        onset = episode.get("onset_step_ids")
        if isinstance(onset, list):
            flagged_steps.update(str(step_id) for step_id in onset if step_id is not None)
        recovery = episode.get("recovery")
        recovery_ids = recovery.get("step_ids") if isinstance(recovery, dict) else None
        if isinstance(recovery_ids, list):
            recovery_step_count += len(recovery_ids)
    return {"problem_count": len(episodes), "flagged_step_count": len(flagged_steps),
            "flagged_step_ids": sorted(flagged_steps), "recovery_step_count": recovery_step_count,
            "flagged_labels": [{"id": label_id, "name": label_name, "count": count}
                for (label_id, label_name), count in sorted(labels.items())]}


def _image_ids(value: Any) -> list[str]:
    return sorted({str(item) for item in value if item is not None}) if isinstance(value, list) else []


def _review_evidence(content: dict | None, review_result: ReviewResult | None) -> dict[str, Any]:
    provenance = review_result.provenance if review_result and isinstance(review_result.provenance, dict) else {}
    usage = provenance.get("usage") if isinstance(provenance.get("usage"), dict) else {}
    if isinstance(provenance.get("evidence"), dict):
        evidence = provenance["evidence"]
    elif isinstance(usage.get("evidence"), dict):
        evidence = usage["evidence"]
    else:
        evidence = provenance
    source_ids = _image_ids(evidence.get("source_image_step_ids"))
    if not source_ids:
        source_ids = sorted({str(step.get("step_id")) for step in (content or {}).get("steps", [])
                             if isinstance(step, dict) and (step.get("screenshot") or step.get("screenshot_path") or step.get("screenshot_url"))
                             and step.get("step_id") is not None})
    supplied_ids = _image_ids(evidence.get("supplied_image_step_ids"))
    omitted_ids = _image_ids(evidence.get("omitted_image_step_ids"))
    cited_ids = _image_ids(evidence.get("cited_image_step_ids"))
    return {"evidence_mode": evidence.get("evidence_mode"),
            "source_image_step_ids": source_ids,
            "supplied_image_step_ids": supplied_ids,
            "omitted_image_step_ids": omitted_ids,
            "cited_image_step_ids": cited_ids,
            "image_selection": copy.deepcopy(evidence.get("image_selection")),
            "omitted_image_reason": evidence.get("omitted_image_reason"),
            "source_image_count": len(source_ids), "supplied_image_count": len(supplied_ids),
            "omitted_image_count": len(omitted_ids), "cited_image_count": len(cited_ids)}


def dataset_task_summary(db: Session, content: dict | None,
                         members: list[BatchMember]) -> dict[str, Any]:
    model_groups: dict[tuple[str, str], dict[str, Any]] = {}
    current_results: list[tuple[ReviewResult, BatchMember]] = []
    historical_results: list[tuple[ReviewResult, BatchMember]] = []
    all_reviews = 0
    for member in members:
        results = db.scalars(select(ReviewResult).where(ReviewResult.member_id == member.id)
                             .order_by(ReviewResult.revision)).all()
        all_reviews += len(results)
        if results:
            current_results.append((results[-1], member))
            historical_results.extend((result, member) for result in results[:-1])
    current_counts = [_review_counts(result.review) for result, _member in current_results]
    historical_counts = [_review_counts(result.review) for result, _member in historical_results]

    def empty_model_group(key: tuple[str, str]) -> dict[str, Any]:
        return {"backend": key[0], "model": key[1],
            "current_review_count": 0, "historical_review_count": 0,
            "current_problem_count": 0, "historical_problem_count": 0,
            "current_recovery_step_count": 0, "historical_recovery_step_count": 0,
            "current_flagged_step_ids": set(), "historical_flagged_step_ids": set(),
            "current_flagged_labels": {}, "historical_flagged_labels": {},
            "supplied_image_step_ids": set(), "omitted_image_step_ids": set(),
            "cited_image_step_ids": set(), "source_image_step_ids": set(),
            "known_cost_usd": 0.0, "unknown_cost_attempts": 0}

    def grouped(result: ReviewResult, member: BatchMember, *, current: bool):
        key = (result.backend or "unknown", result.model or "unknown")
        group = model_groups.setdefault(key, empty_model_group(key))
        counts = _review_counts(result.review)
        prefix = "current" if current else "historical"
        group[f"{prefix}_review_count"] += 1
        group[f"{prefix}_problem_count"] += counts["problem_count"]
        group[f"{prefix}_recovery_step_count"] += counts["recovery_step_count"]
        group[f"{prefix}_flagged_step_ids"].update(counts["flagged_step_ids"])
        for label in counts["flagged_labels"]:
            label_key = (label["id"], label["name"])
            label_counts = group[f"{prefix}_flagged_labels"]
            label_counts[label_key] = label_counts.get(label_key, 0) + label["count"]
        revision = db.get(TaskRevision, member.task_revision_id)
        evidence = _review_evidence(revision.content if revision else None, result)
        for field in ("source_image_step_ids", "supplied_image_step_ids", "omitted_image_step_ids", "cited_image_step_ids"):
            target = "source_image_step_ids" if field == "source_image_step_ids" else field
            group[target].update(evidence[field])

    for result, member in current_results:
        grouped(result, member, current=True)
    for result, member in historical_results:
        grouped(result, member, current=False)

    # Costs belong to attempts, including failed attempts with no saved review.
    total_known_cost = 0.0
    total_unknown_attempts = 0
    for member in members:
        for job in db.scalars(select(Job).where(Job.member_id == member.id)).all():
            attempts = db.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id)).all()
            for attempt in attempts:
                if attempt.cost_usd is None:
                    total_unknown_attempts += 1
                else:
                    total_known_cost += float(attempt.cost_usd)
            key = (db.get(PresetRevision, job.preset_revision_id).backend if db.get(PresetRevision, job.preset_revision_id) else "unknown",
                   db.get(PresetRevision, job.preset_revision_id).model if db.get(PresetRevision, job.preset_revision_id) else "unknown")
            group = model_groups.setdefault(key, empty_model_group(key))
            group["known_cost_usd"] += sum(float(attempt.cost_usd) for attempt in attempts if attempt.cost_usd is not None)
            group["unknown_cost_attempts"] += sum(attempt.cost_usd is None for attempt in attempts)

    models = []
    for _key, group in sorted(model_groups.items()):
        entry = {key: value for key, value in group.items()
                 if not key.endswith("_ids") and not key.endswith("_labels")}
        entry["current_flagged_step_count"] = len(group["current_flagged_step_ids"])
        entry["historical_flagged_step_count"] = len(group["historical_flagged_step_ids"])
        for prefix in ("current", "historical"):
            entry[f"{prefix}_flagged_labels"] = [{"id": label_id, "name": label_name, "count": count}
                for (label_id, label_name), count in sorted(group[f"{prefix}_flagged_labels"].items())]
        for field in ("source_image_step_ids", "supplied_image_step_ids", "omitted_image_step_ids", "cited_image_step_ids"):
            entry[field] = sorted(group[field])
            entry[field.replace("_step_ids", "_count")] = len(group[field])
        models.append(entry)

    labels: dict[tuple[str, str], int] = {}
    current_flagged_steps: set[str] = set()
    historical_flagged_steps: set[str] = set()
    recovery_count = 0
    historical_recovery_count = 0
    for item in current_counts:
        current_flagged_steps.update(item["flagged_step_ids"])
        recovery_count += item["recovery_step_count"]
        for label in item["flagged_labels"]:
            key = (label["id"], label["name"])
            labels[key] = labels.get(key, 0) + label["count"]
    historical_problem_count = 0
    for item in historical_counts:
        historical_flagged_steps.update(item["flagged_step_ids"])
        historical_problem_count += item["problem_count"]
        historical_recovery_count += item["recovery_step_count"]
    source_ids = sorted({str(step.get("step_id")) for step in (content or {}).get("steps", [])
                         if isinstance(step, dict) and (step.get("screenshot") or step.get("screenshot_path") or step.get("screenshot_url"))
                         and step.get("step_id") is not None})
    supplied_ids = sorted({step_id for result, member in current_results
        for step_id in _review_evidence((db.get(TaskRevision, member.task_revision_id).content
                                         if db.get(TaskRevision, member.task_revision_id) else None), result)["supplied_image_step_ids"]})
    omitted_ids = sorted({step_id for result, member in current_results
        for step_id in _review_evidence((db.get(TaskRevision, member.task_revision_id).content
                                         if db.get(TaskRevision, member.task_revision_id) else None), result)["omitted_image_step_ids"]})
    cited_ids = sorted({step_id for result, member in current_results
        for step_id in _review_evidence((db.get(TaskRevision, member.task_revision_id).content
                                         if db.get(TaskRevision, member.task_revision_id) else None), result)["cited_image_step_ids"]})
    return {"run_count": len(members), "saved_review_count": len(current_results),
        "missing_review_count": max(0, len(members) - len(current_results)),
        "review_revision_count": all_reviews, "historical_review_count": len(historical_results),
        "problem_count": sum(item["problem_count"] for item in current_counts),
        "historical_problem_count": historical_problem_count,
        "flagged_step_count": len(current_flagged_steps),
        "historical_flagged_step_count": len(historical_flagged_steps),
        "recovery_step_count": recovery_count,
        "historical_recovery_step_count": historical_recovery_count,
        "flagged_labels": [{"id": label_id, "name": label_name, "count": count}
            for (label_id, label_name), count in sorted(labels.items())],
        "source_image_step_ids": source_ids, "source_image_count": len(source_ids),
        "supplied_image_step_ids": supplied_ids, "supplied_image_count": len(supplied_ids),
        "omitted_image_step_ids": omitted_ids, "omitted_image_count": len(omitted_ids),
        "cited_image_step_ids": cited_ids, "cited_image_count": len(cited_ids),
        "known_cost_usd": total_known_cost, "unknown_cost_attempts": total_unknown_attempts,
        "models": models}


def batch_progress(db: Session, batch: Batch) -> dict[str, Any]:
    members = db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id)).all()
    counts: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    saved_reviews = missing_reviews = 0
    reviewable_members: list[BatchMember] = []
    for member in members:
        counts[member.status] = counts.get(member.status, 0) + 1
        rev = db.get(TaskRevision, member.task_revision_id)
        outcome = (rev.content or {}).get("outcome", "unknown") if rev else "unknown"
        outcomes[str(outcome or "unknown")] = outcomes.get(str(outcome or "unknown"), 0) + 1
        if outcome in ("passed", "failed"):
            reviewable_members.append(member)
            if member_review(db, member):
                saved_reviews += 1
            else:
                missing_reviews += 1
    jobs = db.scalars(select(Job).where(Job.batch_id == batch.id)).all()
    job_status_counts: dict[str, int] = {}
    attempt_count = automatic_retry_count = 0
    known_cost_usd = 0.0
    unknown_cost_attempts = 0
    known_planned_allowance_usd = 0.0
    planned_allowance_complete = True
    job_member_ids = {job.member_id for job in jobs}
    failed_jobs = []
    for job in jobs:
        job_status_counts[job.status] = job_status_counts.get(job.status, 0) + 1
        attempt_count += job.attempt_count
        automatic_retry_count += max(0, job.attempt_count - 1)
        preset = db.get(PresetRevision, job.preset_revision_id)
        if preset and preset.budget_usd is not None:
            known_planned_allowance_usd += float(preset.budget_usd) * job.max_attempts
        else:
            planned_allowance_complete = False
        for attempt in db.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id)).all():
            if attempt.cost_usd is None:
                unknown_cost_attempts += 1
            else:
                known_cost_usd += float(attempt.cost_usd)
        if job.status == "failed":
            member = db.get(BatchMember, job.member_id)
            failed_jobs.append({"job_id": job.id, "task_id": member.task_id if member else None,
                "status": job.status, "error": job.error, "attempt_count": job.attempt_count,
                "max_attempts": job.max_attempts,
                "budget_usd": preset.budget_usd if preset else None})
    pinned = db.get(PresetRevision, batch.preset_revision_id)
    default_max_attempts = min(4, max(1, int(settings.max_job_attempts)))
    for member in reviewable_members:
        if member.id in job_member_ids:
            continue
        if pinned and pinned.budget_usd is not None:
            known_planned_allowance_usd += float(pinned.budget_usd) * default_max_attempts
        else:
            planned_allowance_complete = False
    return {"total": len(members), "completed": counts.get("completed", 0),
            "queued": counts.get("queued", 0), "running": counts.get("running", 0),
            "retrying": counts.get("retrying", 0),
            "failed": counts.get("failed", 0), "awaiting_review": counts.get("awaiting_review", 0),
            "status_counts": counts, "outcome_summary": outcomes,
            "saved_review_count": saved_reviews, "missing_review_count": missing_reviews,
            "job_status_counts": job_status_counts, "attempt_count": attempt_count,
            "retry_count": automatic_retry_count, "failed_jobs": failed_jobs,
            "planned_allowance_usd": known_planned_allowance_usd if planned_allowance_complete else None,
            "known_planned_allowance_usd": known_planned_allowance_usd,
            "known_cost_usd": known_cost_usd, "unknown_cost_attempts": unknown_cost_attempts,
            "planned_job_count": len(reviewable_members),
            "default_max_attempts": default_max_attempts}


def batch_detail(db: Session, batch: Batch) -> dict[str, Any]:
    result = record(batch)
    pinned = db.get(PresetRevision, batch.preset_revision_id)
    if pinned:
        result["preset_id"] = pinned.preset_id
        preset_record = record(pinned)
        preset = db.get(Preset, pinned.preset_id)
        preset_record["name"] = preset.name if preset else "Pinned preset"
        result["preset"] = preset_record
    else:
        result["preset_id"] = None
        result["preset"] = None
    result["progress"] = batch_progress(db, batch)
    waves = db.scalars(select(SyncWave).where(SyncWave.batch_id == batch.id).order_by(SyncWave.number)).all()
    result["waves"] = [record(w) for w in waves]
    grants = []
    for grant in db.scalars(select(BatchGrant).where(BatchGrant.batch_id == batch.id)).all():
        entry = record(grant)
        if grant.team_id:
            team = db.get(Team, grant.team_id)
            entry["team_name"] = team.name if team else None
        if grant.user_id:
            target = db.get(User, grant.user_id)
            entry["user_name"] = target.name if target else None
            entry["email"] = target.email if target else None
        grants.append(entry)
    result["grants"] = grants
    release = db.get(TaxonomyRelease, batch.taxonomy_release_id) if batch.taxonomy_release_id else None
    result["taxonomy_release"] = ({**record(release), "labels": (release.content or {}).get("labels", [])}
                                  if release else None)
    result["batch"] = {key: value for key, value in result.items()
                        if key not in ("progress", "waves", "grants", "batch")}
    result["batch"]["progress"] = result["progress"]
    return result


def run_detail(db: Session, batch: Batch, user: User) -> dict[str, Any]:
    output = batch_detail(db, batch)
    output["archived"] = is_archived(db, "run", batch.id)
    source_ids = list(db.scalars(select(RunSource.dataset_id).where(RunSource.batch_id == batch.id)
                                 .order_by(RunSource.position)).all())
    if not source_ids:
        source_ids = [batch.dataset_id]
    output["dataset_ids"] = source_ids
    source_datasets = []
    for source_id in source_ids:
        dataset = db.get(Dataset, source_id)
        if not dataset:
            continue
        included_tasks = db.scalar(
            select(func.count(func.distinct(BatchMember.task_definition_id)))
            .select_from(BatchMember)
            .join(TaskDefinition, TaskDefinition.id == BatchMember.task_definition_id)
            .where(BatchMember.batch_id == batch.id, TaskDefinition.dataset_id == dataset.id)
        ) or 0
        current_definitions = db.scalars(select(TaskDefinition.id).where(
            TaskDefinition.dataset_id == dataset.id)).all()
        dataset_access = bool(dataset_role(db, dataset, user)) and not is_archived(db, "dataset", dataset.id)
        total_tasks = sum(not is_archived(db, "task", definition_id) for definition_id in current_definitions)
        source_datasets.append({"id": dataset.id, "name": dataset.name,
            "archived": is_archived(db, "dataset", dataset.id),
            "task_count": int(included_tasks), "partial_access": not dataset_access,
            **({"total_task_count": total_tasks} if dataset_access else {})})
    output["source_datasets"] = source_datasets
    configuration = db.scalar(select(RunConfiguration).where(RunConfiguration.batch_id == batch.id))
    pinned = db.get(PresetRevision, batch.preset_revision_id)
    if configuration:
        workflow_id = configuration.workflow_revision_id
        workflow_snapshot = configuration.workflow_snapshot
        execution_snapshot = configuration.execution_snapshot
        rerun_of = configuration.rerun_of_batch_id
        config_revision = configuration.revision
    else:
        workflow_id = None
        workflow_snapshot = None
        execution_snapshot = ({"backend": pinned.backend, "model": pinned.model,
            "reasoning": pinned.reasoning, "budget_usd": pinned.budget_usd,
            "configuration": pinned.configuration} if pinned else {})
        rerun_of, config_revision = None, 1
    output["configuration"] = {"workflow_revision_id": workflow_id,
        "workflow_snapshot": workflow_snapshot, "execution_snapshot": execution_snapshot,
        "revision": config_revision, "rerun_of_run_id": rerun_of}
    return output


def review_problem_count(review: dict | None) -> int:
    episodes = review.get("episodes") if isinstance(review, dict) else None
    return len(episodes) if isinstance(episodes, list) else 0


def visible_batches(db: Session, user: User, include_archived: bool = False) -> list[Batch]:
    rows = db.scalars(select(Batch).where(Batch.workspace_id == user.workspace_id)
                      .order_by(Batch.created_at.desc())).all()
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


@app.get("/api/catalog")
def selection_catalog(include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_user)):
    datasets = db.scalars(select(Dataset).where(Dataset.workspace_id == user.workspace_id)
                          .order_by(Dataset.name)).all()
    datasets = [dataset for dataset in datasets if dataset_role(db, dataset, user) and
                (include_archived or not is_archived(db, "dataset", dataset.id))]
    accessible_datasets = {dataset.id: dataset for dataset in datasets}
    batches = visible_batches(db, user, include_archived)
    run_rows = []
    run_members: dict[str, list[BatchMember]] = {}
    for batch in batches:
        members = db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id)).all()
        run_members[batch.id] = members
        problems = sum(review_problem_count((member_review(db, member).review if member_review(db, member) else None))
                       for member in members)
        sources = list(db.scalars(select(RunSource.dataset_id).where(RunSource.batch_id == batch.id)
                                  .order_by(RunSource.position)).all()) or [batch.dataset_id]
        visible_sources = [source_id for source_id in sources if source_id in accessible_datasets]
        run_rows.append({"id": batch.id, "name": batch.name, "dataset_ids": visible_sources,
            "task_count": len(members), "status": batch.status, "problem_count": problems,
            "archived": is_archived(db, "run", batch.id), "partial_access": len(visible_sources) < len(sources)})
    task_rows, dataset_rows = [], []
    for dataset in datasets:
        definitions = db.scalars(select(TaskDefinition).where(TaskDefinition.dataset_id == dataset.id)
                                 .order_by(TaskDefinition.task_id)).all()
        if not include_archived:
            definitions = [definition for definition in definitions if not is_archived(db, "task", definition.id)]
        problem_total = 0
        run_ids_for_dataset = {batch.id for batch in batches if dataset.id in (
            list(db.scalars(select(RunSource.dataset_id).where(RunSource.batch_id == batch.id)).all()) or [batch.dataset_id])}
        for definition in definitions:
            revision = current_revision(db, definition)
            if not revision:
                continue
            memberships = [member for run_id in run_ids_for_dataset for member in run_members.get(run_id, [])
                           if member.task_definition_id == definition.id]
            problems = sum(review_problem_count((latest.review if (latest := member_review(db, member)) else None))
                           for member in memberships)
            problem_total += problems
            content = revision.content or {}
            task_rows.append({"id": definition.id, "task_definition_id": definition.id,
                "dataset_id": dataset.id, "task_id": definition.task_id,
                "title": content.get("title") or definition.task_id,
                "outcome": content.get("outcome") or "unknown",
                "step_count": len(content.get("steps") or []), "run_count": len({m.batch_id for m in memberships}),
                "problem_count": problems, "archived": is_archived(db, "task", definition.id),
                "summary": dataset_task_summary(db, content, memberships)})
        dataset_rows.append({"id": dataset.id, "name": dataset.name, "task_count": len(definitions),
            "run_count": len(run_ids_for_dataset), "problem_count": problem_total,
            "archived": is_archived(db, "dataset", dataset.id)})
    return {"datasets": dataset_rows, "runs": run_rows, "tasks": task_rows}


@app.post("/api/analytics/query")
def analytics_query(body: AnalyticsQuery, db: Session = Depends(get_db), user: User = Depends(get_user)):
    catalog_datasets = db.scalars(select(Dataset).where(Dataset.workspace_id == user.workspace_id)).all()
    accessible_datasets = {dataset.id: dataset for dataset in catalog_datasets if dataset_role(db, dataset, user) and
        (body.include_archived or not is_archived(db, "dataset", dataset.id))}
    if body.dataset_ids:
        if len(set(body.dataset_ids)) != len(body.dataset_ids) or any(item not in accessible_datasets for item in body.dataset_ids):
            raise HTTPException(404, "Selected dataset not found")
        selected_dataset_ids = set(body.dataset_ids)
    else:
        selected_dataset_ids = set(accessible_datasets)
    batches = visible_batches(db, user, body.include_archived)
    visible_run_ids = {batch.id for batch in batches}
    if body.run_ids:
        if len(set(body.run_ids)) != len(body.run_ids) or not set(body.run_ids) <= visible_run_ids:
            raise HTTPException(404, "Selected run not found")
        selected_run_ids = set(body.run_ids)
    else:
        selected_run_ids = visible_run_ids

    selected_batches = [batch for batch in batches if batch.id in selected_run_ids]
    if not body.dataset_ids:
        # A visible run grant authorizes its members. Include those task definitions
        # in the analytic scope while keeping unrelated tasks in hidden datasets out.
        authorized_member_ids = set(db.scalars(select(BatchMember.task_definition_id).where(
            BatchMember.batch_id.in_(selected_run_ids) if selected_run_ids else False)).all())
        authorized_members = db.scalars(select(TaskDefinition).where(
            TaskDefinition.id.in_(authorized_member_ids) if authorized_member_ids else False)).all()
        accessible_definitions = db.scalars(select(TaskDefinition).where(
            TaskDefinition.dataset_id.in_(accessible_datasets) if accessible_datasets else False)).all()
        definitions_by_id = {definition.id: definition for definition in accessible_definitions}
        definitions_by_id.update({definition.id: definition for definition in authorized_members})
        definitions = list(definitions_by_id.values())
        selected_dataset_ids.update(definition.dataset_id for definition in authorized_members)
    else:
        definitions = db.scalars(select(TaskDefinition).where(TaskDefinition.dataset_id.in_(selected_dataset_ids))
                                 if selected_dataset_ids else select(TaskDefinition).where(False)).all()
    definitions = [definition for definition in definitions if body.include_archived or
                   not is_archived(db, "task", definition.id)]
    if body.task_definition_ids:
        by_id = {definition.id: definition for definition in definitions}
        if len(set(body.task_definition_ids)) != len(body.task_definition_ids) or any(item not in by_id for item in body.task_definition_ids):
            raise HTTPException(404, "Selected task definition not found")
        selected_definition_ids = set(body.task_definition_ids)
    else:
        selected_definition_ids = {definition.id for definition in definitions}

    member_rows: list[BatchMember] = []
    for batch in selected_batches:
        sources = set(db.scalars(select(RunSource.dataset_id).where(RunSource.batch_id == batch.id)).all()) or {batch.dataset_id}
        for member in db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id)).all():
            if member.task_definition_id not in selected_definition_ids:
                continue
            definition = db.get(TaskDefinition, member.task_definition_id)
            if definition and definition.dataset_id in selected_dataset_ids and sources.intersection(selected_dataset_ids):
                member_rows.append(member)

    rows: list[dict[str, Any]] = []
    seen_definitions = set()
    label_counts: dict[tuple[str, str], int] = {}
    outcome_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    absent_frame_steps = missing_artifact_records = broken_source_files = problem_count = recovery_count = 0
    known_cost = 0.0
    unknown_cost_jobs = 0
    unknown_cost_attempts = 0
    for member in member_rows:
        definition = db.get(TaskDefinition, member.task_definition_id)
        revision = db.get(TaskRevision, member.task_revision_id)
        batch = db.get(Batch, member.batch_id)
        if not definition or not revision or not batch:
            continue
        seen_definitions.add(definition.id)
        content = revision.content or {}
        outcome = str(content.get("outcome") or "unknown")
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        status_counts[member.status] = status_counts.get(member.status, 0) + 1
        review_result = member_review(db, member)
        review = review_result.review if review_result else None
        episodes = review.get("episodes", []) if isinstance(review, dict) else []
        if not isinstance(episodes, list):
            episodes = []
        problem_count += len(episodes)
        recovery_step_count = 0
        labels_for_row = []
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            recovery = episode.get("recovery") if isinstance(episode.get("recovery"), dict) else {}
            recovery_step_count += len(recovery.get("step_ids", [])) if isinstance(recovery.get("step_ids"), list) else 0
            label_id = str(episode.get("label_id") or "unlabeled")
            label_name = str(episode.get("label_name") or label_id)
            key = (label_id, label_name)
            label_counts[key] = label_counts.get(key, 0) + 1
            labels_for_row.append({"id": label_id, "name": label_name})
        recovery_count += recovery_step_count
        artifacts = db.scalars(select(StoredArtifact.relative_path).where(StoredArtifact.workspace_id == user.workspace_id,
            StoredArtifact.task_revision_id == revision.id,
            or_(StoredArtifact.member_id == member.id, StoredArtifact.member_id.is_(None)))).all()
        recorded = set(artifacts)
        steps = [step for step in content.get("steps", []) if isinstance(step, dict)]
        absent_frames = sum(1 for step in steps if not (step.get("screenshot") or step.get("screenshot_path")))
        screenshot_paths = [step.get("screenshot") or step.get("screenshot_path") for step in steps
                            if step.get("screenshot") or step.get("screenshot_path")]
        missing_records = sum(1 for path in screenshot_paths if path not in recorded)
        artifact_rows = db.scalars(select(StoredArtifact).where(StoredArtifact.task_revision_id == revision.id,
            StoredArtifact.relative_path.in_(screenshot_paths or ["__none__"]),
            or_(StoredArtifact.member_id == member.id, StoredArtifact.member_id.is_(None)))).all()
        broken_sources = sum(1 for artifact in artifact_rows if artifact.source_relative_path and
                             not _recorded_source_file(artifact.source_relative_path))
        absent_frame_steps += absent_frames
        missing_artifact_records += missing_records
        broken_source_files += broken_sources
        jobs = db.scalars(select(Job).where(Job.member_id == member.id)).all()
        member_known_cost, member_unknown_jobs, member_unknown_attempts = 0.0, 0, 0
        for job in jobs:
            attempts = db.scalars(select(JobAttempt).where(JobAttempt.job_id == job.id)).all()
            job_unknown_attempts = 0
            for attempt in attempts:
                if attempt.cost_usd is None:
                    job_unknown_attempts += 1
                    unknown_cost_attempts += 1
                else:
                    member_known_cost += float(attempt.cost_usd)
                    known_cost += float(attempt.cost_usd)
            if job_unknown_attempts:
                unknown_cost_jobs += 1
                member_unknown_jobs += 1
                member_unknown_attempts += job_unknown_attempts
        rows.append({"run_id": batch.id, "run_name": batch.name, "dataset_id": definition.dataset_id,
            "task_definition_id": definition.id, "task_id": definition.task_id, "task_title": content.get("title") or definition.task_id,
            "task_revision_id": revision.id, "task_revision": revision.revision,
            "member_id": member.id, "review_result_id": review_result.id if review_result else None,
            "review_revision": review_result.revision if review_result else None,
            "status": member.status, "outcome": outcome, "review_kind": member.review_kind,
            "problem_count": len(episodes), "labels": labels_for_row,
            "recovery_step_count": recovery_step_count, "absent_frame_steps": absent_frames,
            "missing_artifact_records": missing_records, "broken_source_files": broken_sources,
            "known_cost_usd": member_known_cost, "unknown_cost_jobs": member_unknown_jobs,
            "unknown_cost_attempts": member_unknown_attempts})

    # Preserve selected tasks with no run membership as explicit not-run rows.
    if not body.run_ids:
        for definition in definitions:
            if definition.id not in selected_definition_ids or definition.id in seen_definitions:
                continue
            revision = current_revision(db, definition)
            if not revision:
                continue
            content = revision.content or {}
            artifacts = set(db.scalars(select(StoredArtifact.relative_path).where(
                StoredArtifact.task_revision_id == revision.id, StoredArtifact.member_id.is_(None))).all())
            steps = [step for step in content.get("steps", []) if isinstance(step, dict)]
            absent_frames = sum(1 for step in steps if not (step.get("screenshot") or step.get("screenshot_path")))
            screenshot_paths = [step.get("screenshot") or step.get("screenshot_path") for step in steps
                                if step.get("screenshot") or step.get("screenshot_path")]
            missing_records = sum(1 for path in screenshot_paths if path not in artifacts)
            artifact_rows = db.scalars(select(StoredArtifact).where(StoredArtifact.task_revision_id == revision.id,
                StoredArtifact.relative_path.in_(screenshot_paths or ["__none__"]),
                StoredArtifact.member_id.is_(None))).all()
            broken_sources = sum(1 for artifact in artifact_rows if artifact.source_relative_path and
                                 not _recorded_source_file(artifact.source_relative_path))
            absent_frame_steps += absent_frames
            missing_artifact_records += missing_records
            broken_source_files += broken_sources
            outcome = str(content.get("outcome") or "unknown")
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            status_counts["not_run"] = status_counts.get("not_run", 0) + 1
            rows.append({"run_id": None, "run_name": None, "dataset_id": definition.dataset_id,
                "task_definition_id": definition.id, "task_id": definition.task_id, "task_title": content.get("title") or definition.task_id,
                "task_revision_id": revision.id, "task_revision": revision.revision,
                "member_id": None, "review_result_id": None, "review_revision": None,
                "status": "not_run", "outcome": outcome, "review_kind": None,
                "problem_count": 0, "labels": [], "recovery_step_count": 0,
                "absent_frame_steps": absent_frames, "missing_artifact_records": missing_records,
                "broken_source_files": broken_sources, "known_cost_usd": 0.0, "unknown_cost_jobs": 0,
                "unknown_cost_attempts": 0})
    return {"filters": {"dataset_ids": sorted(selected_dataset_ids), "run_ids": sorted(selected_run_ids),
                         "task_definition_ids": sorted(selected_definition_ids)},
        "counts": {"task_definitions": len({row["task_definition_id"] for row in rows}),
            "selected_task_definitions": len(selected_definition_ids), "rows": len(rows),
            "run_members": len(member_rows), "problem_episodes": problem_count,
            "recovery_steps": recovery_count, "absent_frame_steps": absent_frame_steps,
            "missing_artifact_records": missing_artifact_records, "broken_source_files": broken_source_files,
            "missing_evidence": absent_frame_steps + missing_artifact_records + broken_source_files,
            "outcomes": outcome_counts, "statuses": status_counts,
            "cost_usd": None if unknown_cost_jobs else known_cost,
            "known_cost_usd": known_cost, "unknown_cost_jobs": unknown_cost_jobs,
            "unknown_cost_attempts": unknown_cost_attempts},
        "labels": [{"id": label_id, "name": label_name, "count": count}
                   for (label_id, label_name), count in sorted(label_counts.items())],
        "rows": rows}


@app.post("/api/analytics/compare")
def analytics_compare(body: AnalyticsCompare, db: Session = Depends(get_db), user: User = Depends(get_user)):
    if len(set(body.result_ids)) != len(body.result_ids):
        raise HTTPException(422, "result_ids must be unique")
    results = []
    for result_id in body.result_ids:
        result = db.get(ReviewResult, result_id)
        if not result:
            raise HTTPException(404, "Review result not found")
        member = db.get(BatchMember, result.member_id)
        if not member:
            raise HTTPException(404, "Review member not found")
        get_batch(db, member.batch_id, user)
        results.append((result, member))
    keys = {(member.task_definition_id, member.task_revision_id) for _result, member in results}
    if len(keys) != 1:
        raise HTTPException(422, "Compare only results aligned to the same task definition and task revision")
    first_member = results[0][1]
    task_definition = db.get(TaskDefinition, first_member.task_definition_id)
    fields = ("review_kind", "steps", "episodes")
    differences = []
    for field in fields:
        values = [{"result_id": result.id, "value": result.review.get(field)} for result, _member in results]
        if any(canonical(item["value"]) != canonical(values[0]["value"]) for item in values[1:]):
            differences.append({"field": field, "values": values})
    revision = db.get(TaskRevision, first_member.task_revision_id)
    return {"aligned": {"task_definition_id": first_member.task_definition_id,
        "task_id": task_definition.task_id if task_definition else first_member.task_id,
        "task_revision_id": first_member.task_revision_id,
        "task_revision": revision.revision if revision else None},
        "results": [{"id": result.id, "member_id": member.id, "run_id": member.batch_id,
            "task_id": member.task_id,
            "revision": result.revision, "review_kind": result.review_kind,
            "backend": result.backend, "model": result.model, "review": result.review,
            "created_at": iso(result.created_at)} for result, member in results],
        "differences": differences, "verdict": None}


def execution_snapshot(execution: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    backend = execution.get("backend")
    model = execution.get("model")
    budget = execution.get("budget_usd")
    if backend == "saved_replay":
        if model not in (None, "retained-poc"):
            raise HTTPException(422, "saved_replay must use model 'retained-poc'")
        model = "retained-poc"
        budget = 0.0 if budget is None else budget
    elif not model or budget is None or not 0 < float(budget) <= 0.5:
        raise HTTPException(422, "Live reviewer execution needs a model and a budget no greater than $0.50")
    config = copy.deepcopy(execution.get("configuration") or {})
    for key in ("timeout_seconds", "max_output_tokens", "max_images"):
        if key in config and not isinstance(config[key], int):
            raise HTTPException(422, f"{key} must be an integer")
    config.setdefault("timeout_seconds", 90)
    config.setdefault("max_output_tokens", 2048)
    config.setdefault("max_images", 32)
    if not 15 <= config["timeout_seconds"] <= 120:
        raise HTTPException(422, "timeout_seconds must be between 15 and 120")
    if not 256 <= config["max_output_tokens"] <= 4096:
        raise HTTPException(422, "max_output_tokens must be between 256 and 4096")
    if not 0 <= config["max_images"] <= 32:
        raise HTTPException(422, "max_images must be between 0 and 32")
    secret_keys = {"api_key", "apikey", "secret", "password", "token", "accesstoken",
                   "refreshtoken", "credential", "credentials", "authorization"}
    def check_secrets(value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
                if normalized in secret_keys:
                    raise HTTPException(422, "Execution configuration cannot contain credentials or secrets")
                check_secrets(item)
        elif isinstance(value, list):
            for item in value:
                check_secrets(item)
    check_secrets(config)
    try:
        if len(json.dumps(config, allow_nan=False, separators=(",", ":")).encode("utf-8")) > 64 * 1024:
            raise HTTPException(422, "Execution configuration exceeds 64 KB")
    except (TypeError, ValueError):
        raise HTTPException(422, "Execution configuration must contain JSON data") from None
    config["workflow_snapshot"] = copy.deepcopy(workflow)
    return {"backend": backend, "model": model, "reasoning": execution.get("reasoning") or "low",
            "budget_usd": budget, "budget_kind": "none" if backend == "saved_replay" else "estimate_only",
            "budget_enforced": backend == "saved_replay", "configuration": config}


def create_run_preset(db: Session, user: User, snapshot: dict[str, Any]) -> PresetRevision:
    preset = Preset(workspace_id=user.workspace_id, name="__run_config__" + uid(), created_by=user.id)
    db.add(preset)
    db.flush()
    revision = PresetRevision(preset_id=preset.id, revision=1, backend=snapshot["backend"],
        model=snapshot["model"], reasoning=snapshot["reasoning"], budget_usd=snapshot["budget_usd"],
        configuration=copy.deepcopy(snapshot["configuration"]),
        config_hash=digest(snapshot), created_by=user.id)
    db.add(revision)
    db.flush()
    return revision


def add_member(db: Session, batch: Batch, definition: TaskDefinition, revision: TaskRevision, wave_id: str,
               user: User, status: str | None = None) -> BatchMember:
    existing = db.scalar(select(BatchMember).where(BatchMember.batch_id == batch.id,
                                                    BatchMember.task_revision_id == revision.id))
    if existing:
        return existing
    content = revision.content
    route = "failure_analysis" if content.get("outcome") == "failed" else "pass_recovery" if content.get("outcome") == "passed" else None
    review = content.get("review")
    member_status = status or "awaiting_review"
    member = BatchMember(batch_id=batch.id, task_definition_id=definition.id,
                         task_revision_id=revision.id, wave_id=wave_id,
                         task_id=definition.task_id, review_kind=route,
                         status=member_status)
    db.add(member)
    db.flush()
    if review and member_status == "completed":
        preset = db.get(PresetRevision, batch.preset_revision_id)
        db.add(ReviewResult(member_id=member.id, revision=1, review_kind=route or review.get("review_kind", "unknown"),
                            schema_version=review.get("schema_version"), source_kind="saved_replay",
                            backend="saved_replay", model=content.get("original_model") or "model not recorded",
                            review=copy.deepcopy(review),
                            provenance={"mode": "saved_replay", "original_run_id": content.get("original_run_id") or (content.get("provenance") or {}).get("run_id"),
                                        "original_model": content.get("original_model"),
                                        "original_reasoning_effort": content.get("original_reasoning_effort"),
                                        "original_usage": content.get("usage"),
                                        "original_prompt_sha256": content.get("original_prompt_sha256"),
                                        "new_inference": False,
                                        "preset_revision_id": preset.id if preset else None}))
    # Carry dataset-revision ZIP evidence into a member-scoped authorization row.
    copy_revision_artifacts_to_member(db, user.workspace_id, revision, member)
    db.flush()
    register_evidence(db, user, revision, member, content)
    return member


def seed_first_workspace(db: Session, user: User):
    """Import the retained POC's latest completed fixture without invoking a model."""
    if not settings.seed_poc:
        return
    run_path = PROJECT_ROOT / "poc" / "runs" / "latest" / "run.json"
    if not run_path.is_file():
        return
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        if run.get("status") != "completed" or not isinstance(run.get("tasks"), list):
            return
        tasks = run["tasks"][-5:]
    except (OSError, json.JSONDecodeError):
        return
    lock_taxonomy_workspace(db, user.workspace_id)
    dataset = Dataset(workspace_id=user.workspace_id, name="Saved POC examples",
                      description="Five retained trajectory reviews. These are replayed source evidence, not new inference.",
                      source_adapter="cuautoreview", created_by=user.id)
    db.add(dataset)
    preset = Preset(workspace_id=user.workspace_id, name="Saved replay (retained evidence)", created_by=user.id)
    db.add(preset)
    db.flush()
    config = {"replay": True, "description": "Replays retained POC evidence; makes no model calls."}
    revision = PresetRevision(preset_id=preset.id, revision=1, backend="saved_replay", model="retained-poc",
                              reasoning="none", budget_usd=0.0, configuration=config,
                              config_hash=digest(config), created_by=user.id)
    db.add(revision)
    for task in tasks:
        task_id = str(task.get("task_id", ""))
        if not task_id:
            continue
        content = copy.deepcopy(task)
        content["original_run_id"] = run.get("run_id")
        content["provenance"] = {"run_id": run.get("run_id"), "run_status": run.get("status"),
                                 "saved_replay": True, "source": task.get("source", {})}
        content["original_model"] = run.get("model")
        content["original_dedup_model"] = run.get("dedup_model")
        content["original_reasoning_effort"] = run.get("reasoning_effort")
        content["original_prompt_sha256"] = copy.deepcopy(run.get("prompt_sha256"))
        defn = TaskDefinition(dataset_id=dataset.id, task_id=task_id)
        db.add(defn)
        db.flush()
        task_rev = TaskRevision(task_definition_id=defn.id, revision=1, source_revision=digest(content), content=content)
        db.add(task_rev)
        db.flush()
        defn.current_revision_id = task_rev.id
    # Wave and batch reference each other; insert the batch to materialize its generated ID.
    batch = Batch(workspace_id=user.workspace_id, dataset_id=dataset.id,
                  name="Retained POC replay", description="Fixture evidence from the most recent completed POC run.",
                  mode="fixed", preset_revision_id=revision.id, status="completed", created_by=user.id)
    db.add(batch)
    db.flush()
    wave = SyncWave(batch_id=batch.id, number=1, sync_key="seed-initial", task_count=len(tasks), created_by=user.id)
    db.add(wave)
    db.flush()
    definitions = {item.task_id: item for item in task_definitions(db, dataset.id)}
    for definition in definitions.values():
        task_rev = current_revision(db, definition)
        if task_rev:
            add_member(db, batch, definition, task_rev, wave.id, user, status="completed" if task_rev.content.get("review") else "awaiting_review")
    # Keep the taxonomy as an editable proposal draft. No consolidation or inference runs here.
    proposals_path = PROJECT_ROOT / "poc" / "runs" / str(run.get("run_id")) / "proposals.json"
    try:
        pool = json.loads(proposals_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pool = {"proposals": []}
    seed_base_hash = digest({"labels": []})
    for item in pool.get("proposals", []):
        proposal = TaxonomyProposal(workspace_id=user.workspace_id, kind="label",
                                    label_id=item.get("id") or item.get("target_label_id") or None,
                                    base_hash=seed_base_hash, created_by=user.id)
        db.add(proposal)
        db.flush()
        body = {"name": item.get("name") or "Untitled label", "description": item.get("description") or "",
                "evidence_refs": item.get("evidence_refs") or []}
        pr = ProposalRevision(proposal_id=proposal.id, revision=1, name=body["name"], description=body["description"],
                              evidence_refs=body["evidence_refs"], content_hash=digest(body), base_revision_hash=None,
                              change_type="create", created_by=user.id)
        db.add(pr)
        db.flush()
        proposal.latest_revision_id = pr.id
    activity(db, user, "workspace.seeded", "workspace", user.workspace_id,
             task_count=len(tasks), run_id=run.get("run_id"), saved_replay=True, inference_calls=0)


def startup():
    init_db(engine)
    if settings.object_store_backend == "s3":
        try:
            import boto3
            client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.aws_region)
            buckets = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
            if settings.s3_bucket not in buckets:
                client.create_bucket(Bucket=settings.s3_bucket)
        except Exception:
            # A transient object-store startup failure should not prevent login/API use.
            app.state.object_store_startup_error = "Object store initialization failed"
    app.state.outbox_relay_task = asyncio.create_task(_outbox_background_loop())


async def _outbox_background_loop():
    """The API owns outbox timing; the Celery worker runs without Beat."""
    from .queue import recover_expired_leases, relay_outbox
    while True:
        try:
            await asyncio.to_thread(relay_outbox.run)
            await asyncio.to_thread(recover_expired_leases.run)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Avoid logging broker URLs, exception text, or environment data.
            logger.warning("Outbox poll failed (%s)", type(exc).__name__)
        await asyncio.sleep(1)


async def shutdown():
    task = getattr(app.state, "outbox_relay_task", None)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@app.get("/api/health")
def health():
    return {"status": "ok", "queue_mode": "sql_outbox_celery", "object_store": settings.object_store_backend}


@app.post("/api/auth/signup")
def signup(body: Signup, response: Response, db: Session = Depends(get_db),
           _bootstrap_lock=Depends(signup_transaction_lock)):
    email = body.email
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    first = db.scalar(select(func.count(User.id))) == 0
    workspace = db.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
    if not workspace:
        workspace = Workspace(name="Local workspace")
        db.add(workspace)
        db.flush()
    user = User(workspace_id=workspace.id, name=body.name.strip(), email=email,
                password_hash=hash_password(body.password), role="admin" if first else "viewer")
    db.add(user)
    try:
        db.flush()
        if first:
            seed_first_workspace(db, user)
        token = new_session_token()
        db.add(LoginSession(token_hash=token_digest(token), user_id=user.id,
                            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours)))
        activity(db, user, "auth.signup", "user", user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account creation conflicted with another signup")
    response.set_cookie(settings.session_cookie, token, max_age=settings.session_ttl_hours * 3600,
                        httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
    return me_record(user)


def me_record(user: User) -> dict[str, Any]:
    return {"id": user.id, "workspace_id": user.workspace_id, "name": user.name, "email": user.email,
            "role": user.role, "active": user.active}


@app.post("/api/auth/login")
def login(body: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    token = new_session_token()
    db.add(LoginSession(token_hash=token_digest(token), user_id=user.id,
                        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours)))
    activity(db, user, "auth.login", "user", user.id)
    db.commit()
    response.set_cookie(settings.session_cookie, token, max_age=settings.session_ttl_hours * 3600,
                        httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
    return me_record(user)


@app.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    raw = request.cookies.get(settings.session_cookie)
    if raw:
        session = db.get(LoginSession, token_digest(raw))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(settings.session_cookie, path="/")


@app.get("/api/auth/me")
def auth_me(user: User = Depends(get_user)):
    return me_record(user)


@app.get("/api/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(get_user)):
    workspace_wide = user.role in ("admin", "manager")
    batch_ids = visible_batch_ids(db, user)
    if workspace_wide:
        batch_count = db.scalar(select(func.count(Batch.id)).where(Batch.workspace_id == user.workspace_id)) or 0
        dataset_count = db.scalar(select(func.count(Dataset.id)).where(Dataset.workspace_id == user.workspace_id)) or 0
        task_count = db.scalar(select(func.count(BatchMember.id)).join(Batch, BatchMember.batch_id == Batch.id)
                                .where(Batch.workspace_id == user.workspace_id)) or 0
    elif batch_ids:
        batch_count = len(batch_ids)
        dataset_count = db.scalar(select(func.count(distinct(Batch.dataset_id))).where(Batch.id.in_(batch_ids))) or 0
        task_count = db.scalar(select(func.count(BatchMember.id)).where(BatchMember.batch_id.in_(batch_ids))) or 0
    else:
        batch_count = dataset_count = task_count = 0
    job_counts = {
        status: (db.scalar(select(func.count(Job.id)).where(
            Job.workspace_id == user.workspace_id, Job.status == status,
            *([] if workspace_wide else [Job.batch_id.in_(batch_ids)]))) or 0) if (workspace_wide or batch_ids) else 0
        for status in ("queued", "running", "failed", "completed")
    }
    recent_query = select(Batch).where(Batch.workspace_id == user.workspace_id)
    if not workspace_wide:
        recent_query = recent_query.where(Batch.id.in_(batch_ids)) if batch_ids else recent_query.where(False)
    recent = db.scalars(recent_query.order_by(Batch.created_at.desc()).limit(5)).all()
    event_query = select(ActivityEvent).where(ActivityEvent.workspace_id == user.workspace_id)
    if not workspace_wide:
        event_query = event_query.where(ActivityEvent.actor_id == user.id)
    events = db.scalars(event_query.order_by(ActivityEvent.created_at.desc()).limit(12)).all()
    counts = {"datasets": dataset_count, "batches": batch_count, "tasks": task_count,
              "jobs": sum(job_counts.values())}
    return {"counts": counts, "datasets": dataset_count, "batches": batch_count, "jobs": job_counts,
            "tasks": task_count,
            "recent_batches": [batch_detail(db, b) for b in recent],
            "activity": [record(e) for e in events],
            "provider_mode": "explicit opt-in only", "queue_mode": "Celery + SQL outbox",
            "storage_mode": settings.object_store_backend,
            "seed_replay": any(b.name == "Retained POC replay" for b in recent)}


@app.get("/api/users")
def users(page: int = 1, per_page: int = 50, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    query = select(User).where(User.workspace_id == user.workspace_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    results = db.scalars(query.order_by(User.name).offset((page - 1) * per_page).limit(min(per_page, 200))).all()
    return {"items": [me_record(u) for u in results], "total": total}


@app.patch("/api/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    target = db.get(User, user_id)
    if not target or target.workspace_id != user.workspace_id:
        raise HTTPException(404, "User not found")
    if target.id == user.id and body.role and body.role != "admin":
        raise HTTPException(409, "You cannot remove your own administrator role")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(target, key, value)
    activity(db, user, "user.updated", "user", target.id)
    db.commit()
    return me_record(target)


@app.get("/api/teams")
def teams(page: int = 1, per_page: int = 50, db: Session = Depends(get_db), user: User = Depends(get_user)):
    query = select(Team).where(Team.workspace_id == user.workspace_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(Team.name).offset((page - 1) * per_page).limit(min(per_page, 200))).all()
    result = []
    for team in items:
        item = record(team)
        item["members"] = [me_record(db.get(User, m.user_id)) for m in db.scalars(select(TeamMember).where(TeamMember.team_id == team.id)).all()]
        result.append(item)
    return {"items": result, "total": total}


@app.post("/api/teams")
def create_team(body: TeamCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    team = Team(workspace_id=user.workspace_id, name=body.name.strip(), description=body.description, created_at=utcnow())
    db.add(team)
    activity(db, user, "team.created", "team", team.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A team with that name already exists")
    return record(team)


@app.patch("/api/teams/{team_id}")
def update_team(team_id: str, body: TeamUpdate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    team = db.get(Team, team_id)
    if not team or team.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(team, key, value)
    db.commit()
    return record(team)


@app.delete("/api/teams/{team_id}", status_code=204)
def delete_team(team_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    team = db.get(Team, team_id)
    if not team or team.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team not found")
    db.delete(team)
    db.commit()


@app.post("/api/teams/{team_id}/members")
def add_team_member(team_id: str, body: AddTeamMember, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    team, target = db.get(Team, team_id), db.get(User, body.user_id)
    if not team or team.workspace_id != user.workspace_id or not target or target.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team or user not found")
    if not db.scalar(select(TeamMember.id).where(TeamMember.team_id == team.id, TeamMember.user_id == target.id)):
        db.add(TeamMember(team_id=team.id, user_id=target.id))
        db.commit()
    return {"team_id": team.id, "user_id": target.id}


@app.delete("/api/teams/{team_id}/members/{user_id}", status_code=204)
def remove_team_member(team_id: str, user_id: str, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    team = db.get(Team, team_id)
    if not team or team.workspace_id != user.workspace_id:
        raise HTTPException(404, "Team not found")
    member = db.scalar(select(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id))
    if member:
        db.delete(member)
        db.commit()


@app.get("/api/datasets")
def datasets(page: int = 1, per_page: int = 50, include_archived: bool = False,
             db: Session = Depends(get_db), user: User = Depends(get_user)):
    query = select(Dataset).where(Dataset.workspace_id == user.workspace_id)
    all_items = db.scalars(query.order_by(Dataset.updated_at.desc())).all()
    visible = [d for d in all_items if dataset_role(db, d, user) and
               (include_archived or not is_archived(db, "dataset", d.id))]
    total = len(visible)
    items = visible[max(page - 1, 0) * min(per_page, 200):max(page - 1, 0) * min(per_page, 200) + min(per_page, 200)]
    output = []
    for d in items:
        item = record(d)
        item["archived"] = is_archived(db, "dataset", d.id)
        definitions = db.scalars(select(TaskDefinition).where(TaskDefinition.dataset_id == d.id)).all()
        if not include_archived:
            definitions = [definition for definition in definitions if not is_archived(db, "task", definition.id)]
        item["task_count"] = len(definitions)
        batches_for_dataset = db.scalars(select(Batch).outerjoin(RunSource, RunSource.batch_id == Batch.id).where(
            Batch.workspace_id == user.workspace_id, or_(Batch.dataset_id == d.id, RunSource.dataset_id == d.id))
            .order_by(Batch.created_at.desc()).distinct()).all()
        dataset_batches = [b for b in batches_for_dataset if _allowed(db, b.id, user) and
                           (include_archived or not is_archived(db, "run", b.id))]
        covered = db.scalars(select(BatchMember.task_definition_id).join(TaskDefinition,
            TaskDefinition.id == BatchMember.task_definition_id).where(TaskDefinition.dataset_id == d.id,
            BatchMember.batch_id.in_([b.id for b in dataset_batches]) if dataset_batches else False)).all()
        item["run_count"] = len(dataset_batches)
        item["membership_coverage"] = {"tasks_in_runs": len(set(covered)), "tasks_total": len(definitions)}
        item["batches"] = [batch_detail(db, b) for b in dataset_batches]
        output.append(item)
    return {"items": output, "total": total}


@app.post("/api/datasets")
def create_dataset(body: DatasetCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    dataset = Dataset(workspace_id=user.workspace_id, name=body.name.strip(), description=body.description,
                      source_adapter=body.source_adapter, created_by=user.id)
    db.add(dataset)
    activity(db, user, "dataset.created", "dataset", dataset.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A dataset with that name already exists")
    return record(dataset)


@app.get("/api/datasets/{dataset_id}")
def dataset_detail(dataset_id: str, include_archived: bool = False,
                   db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, include_archived=include_archived)
    output = record(dataset)
    output["archived"] = is_archived(db, "dataset", dataset.id)
    tasks = []
    for definition in task_definitions(db, dataset.id):
        if not include_archived and is_archived(db, "task", definition.id):
            continue
        rev = current_revision(db, definition)
        if rev:
            item = task_view(db, rev.content, rev.id, definition.task_id, rev.revision)
            item["task_definition_id"] = definition.id
            item["archived_at"] = (db.scalar(select(ObjectArchive.archived_at).where(
                ObjectArchive.object_type == "task", ObjectArchive.object_id == definition.id)))
            if item["archived_at"]:
                item["archived_at"] = iso(item["archived_at"])
            tasks.append(item)
    batches_for_dataset = db.scalars(select(Batch).outerjoin(RunSource, RunSource.batch_id == Batch.id).where(
        Batch.workspace_id == user.workspace_id, or_(Batch.dataset_id == dataset.id, RunSource.dataset_id == dataset.id))
        .order_by(Batch.created_at.desc()).distinct()).all()
    batches = [batch for batch in batches_for_dataset
               if _allowed(db, batch.id, user) and (include_archived or not is_archived(db, "run", batch.id))]
    visible_task_ids = {item["task_definition_id"] for item in tasks}
    included_by_run: dict[str, set[str]] = {}
    batch_outputs = []
    for batch in batches:
        included_ids = set(db.scalars(select(BatchMember.task_definition_id).join(TaskDefinition,
            TaskDefinition.id == BatchMember.task_definition_id).where(BatchMember.batch_id == batch.id,
            TaskDefinition.dataset_id == dataset.id)).all()) & visible_task_ids
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
                memberships.extend(db.scalars(select(BatchMember).where(
                    BatchMember.batch_id == batch_id,
                    BatchMember.task_definition_id == definition_id)).all())
        item["summary"] = dataset_task_summary(db, item, memberships)
    output["tasks"] = tasks
    output["batches"] = batch_outputs
    output["run_count"] = len(batches)
    output["membership_coverage"] = {"tasks_in_runs": len(set().union(*included_by_run.values()))
        if included_by_run else 0, "tasks_total": len(tasks)}
    return output


@app.get("/api/workflows")
def workflows(user: User = Depends(get_user)):
    return {"items": workflow_catalog()}


def dataset_shares_response(db: Session, dataset: Dataset) -> dict[str, Any]:
    shares = db.scalars(select(DatasetShare).where(DatasetShare.dataset_id == dataset.id,
        DatasetShare.workspace_id == dataset.workspace_id)).all()
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


@app.get("/api/directory")
def share_directory(q: str = "", limit: int = 20, db: Session = Depends(get_db),
                    user: User = Depends(require_role("admin", "manager"))):
    needle = q.strip().lower()
    limit = min(max(limit, 1), 50)
    users_query = select(User).where(User.workspace_id == user.workspace_id, User.active.is_(True))
    teams_query = select(Team).where(Team.workspace_id == user.workspace_id)
    if needle:
        pattern = f"%{needle}%"
        users_query = users_query.where(or_(func.lower(User.name).like(pattern), func.lower(User.email).like(pattern)))
        teams_query = teams_query.where(func.lower(Team.name).like(pattern))
    users_out = [{"id": row.id, "name": row.name, "email": row.email} for row in
                 db.scalars(users_query.order_by(User.name).limit(limit)).all()]
    teams_out = [{"id": row.id, "name": row.name} for row in
                 db.scalars(teams_query.order_by(Team.name).limit(limit)).all()]
    return {"users": users_out, "teams": teams_out}


@app.get("/api/datasets/{dataset_id}/shares")
def get_dataset_shares(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    return dataset_shares_response(db, dataset)


@app.put("/api/datasets/{dataset_id}/shares")
def put_dataset_shares(dataset_id: str, body: DatasetSharesUpdate,
                       db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    if len({item.target_id for item in body.users}) != len(body.users) or len({item.target_id for item in body.teams}) != len(body.teams):
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
        rows.append(DatasetShare(workspace_id=user.workspace_id, dataset_id=dataset.id,
            target_type="workspace", target_id=None, role="viewer", created_by=user.id))
    rows.extend(DatasetShare(workspace_id=user.workspace_id, dataset_id=dataset.id,
        target_type="user", target_id=item.target_id, role=item.role, created_by=user.id) for item in body.users)
    rows.extend(DatasetShare(workspace_id=user.workspace_id, dataset_id=dataset.id,
        target_type="team", target_id=item.target_id, role=item.role, created_by=user.id) for item in body.teams)
    db.add_all(rows)
    activity(db, user, "dataset.shared", "dataset", dataset.id,
             workspace_shared=body.workspace_shared, user_count=len(body.users), team_count=len(body.teams))
    db.commit()
    return dataset_shares_response(db, dataset)


@app.post("/api/datasets/{dataset_id}/archive")
def archive_dataset(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "dataset", dataset.id, True)


@app.post("/api/datasets/{dataset_id}/restore")
def restore_dataset(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "dataset", dataset.id, False)


@app.post("/api/tasks/{task_definition_id}/archive")
def archive_task_definition(task_definition_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition:
        raise HTTPException(404, "Task not found")
    dataset = require_dataset_access(db, definition.dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "task", definition.id, True)


@app.post("/api/tasks/{task_definition_id}/restore")
def restore_task_definition(task_definition_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition:
        raise HTTPException(404, "Task not found")
    require_dataset_access(db, definition.dataset_id, user, "manager", include_archived=True)
    return set_archived(db, user, "task", definition.id, False)


@app.get("/api/datasets/{dataset_id}/tasks/{task_definition_id}")
def dataset_task_detail(dataset_id: str, task_definition_id: str, include_archived: bool = False,
                        db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "viewer", include_archived=include_archived)
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition or definition.dataset_id != dataset.id:
        raise HTTPException(404, "Task not found")
    archived_at = db.scalar(select(ObjectArchive.archived_at).where(ObjectArchive.object_type == "task",
        ObjectArchive.object_id == definition.id))
    if archived_at and not include_archived:
        raise HTTPException(404, "Task not found")
    current = current_revision(db, definition)
    current_content = task_view(db, current.content, current.id, definition.task_id, current.revision) if current else None
    revisions = db.scalars(select(TaskRevision).where(TaskRevision.task_definition_id == definition.id)
                           .order_by(TaskRevision.revision)).all()
    memberships = db.scalars(select(BatchMember).where(BatchMember.task_definition_id == definition.id)
                             .order_by(BatchMember.created_at)).all()
    batch_ids = {member.batch_id for member in memberships}
    failed_by_batch = {}
    if batch_ids:
        failed_by_batch = {batch_id: count for batch_id, count in db.execute(
            select(BatchMember.batch_id, func.count(BatchMember.id))
            .where(BatchMember.batch_id.in_(batch_ids), BatchMember.status == "failed")
            .group_by(BatchMember.batch_id)).all()}
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
        reviews = db.scalars(select(ReviewResult).where(ReviewResult.member_id == member.id)
                             .order_by(ReviewResult.revision)).all()
        jobs = db.scalars(select(Job).where(Job.member_id == member.id).order_by(Job.created_at)).all()
        latest_review = reviews[-1] if reviews else None
        content = revision.content if revision else {}
        review_summary = _review_counts(latest_review.review if latest_review else None)
        review_summary["review_count"] = len(reviews)
        review_summary["review_status"] = "saved" if latest_review else "missing"
        review_summary.update(_review_evidence(content, latest_review))
        visible_members.append(member)
        history.append({"run_id": batch.id, "run_name": batch.name, "batch_id": batch.id,
            "created_at": iso(batch.created_at),
            "failed_task_count": int(failed_by_batch.get(batch.id, 0)),
            "member_id": member.id, "status": member.status, "review_kind": member.review_kind,
            "outcome": (content or {}).get("outcome", "unknown"),
            "score": (content or {}).get("score"),
            "job_id": jobs[0].id if jobs else None,
            "jobs": [job_detail(db, job) for job in jobs],
            "review_summary": review_summary,
            "review_provenance": (copy.deepcopy(latest_review.provenance)
                                  if latest_review and isinstance(latest_review.provenance, dict) else None),
            "task_revision_id": member.task_revision_id, "task_revision_number": revision.revision if revision else None,
            "reviews": [record(item) for item in reviews]})
    return {"dataset_id": dataset.id,
        "task_definition": {"id": definition.id, "task_id": definition.task_id,
                            "created_at": iso(definition.created_at), "archived_at": iso(archived_at)},
        "current_revision": ({"id": current.id, "revision": current.revision,
            "source_revision": current.source_revision, "content": current_content,
            "created_at": iso(current.created_at)} if current else None),
        "revisions": [{"id": rev.id, "revision": rev.revision, "source_revision": rev.source_revision,
                       "created_at": iso(rev.created_at)} for rev in revisions],
        "summary": dataset_task_summary(db, current.content if current else None, visible_members),
        "runs": history}


@app.get("/api/datasets/{dataset_id}/tasks/{task_definition_id}/export")
def export_dataset_task(dataset_id: str, task_definition_id: str,
                        format: str = Query("json", pattern="^(json|yaml)$"),
                        include_archived: bool = False,
                        db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, include_archived=include_archived)
    definition = db.get(TaskDefinition, task_definition_id)
    if not definition or definition.dataset_id != dataset.id or (is_archived(db, "task", task_definition_id) and not include_archived):
        raise HTTPException(404, "Task not found")
    revision = current_revision(db, definition)
    if not revision:
        raise HTTPException(404, "Task revision not found")
    content = task_view(db, revision.content, revision.id, definition.task_id)
    if format == "yaml":
        return PlainTextResponse(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), media_type="application/yaml")
    return content


@app.post("/api/datasets/{dataset_id}/import")
async def import_dataset(dataset_id: str, body: DatasetImport, request: Request,
                         db: Session = Depends(get_db), user: User = Depends(get_user)):
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
        if any(not isinstance(step.get("evidence_refs", []), list) or
               any(not isinstance(ref, str) for ref in step.get("evidence_refs", [])) for step in steps):
            raise HTTPException(422, f"Task {task_id}: evidence_refs must be arrays of strings")
        if any(step.get("screenshot") is not None and not isinstance(step["screenshot"], str) for step in steps):
            raise HTTPException(422, f"Task {task_id}: screenshot paths must be strings")
        if cleaned.get("review") is not None and (not isinstance(cleaned["review"], dict) or
                not isinstance(cleaned["review"].get("steps", []), list) or
                any(not isinstance(step, dict) for step in cleaned["review"].get("steps", []))):
            raise HTTPException(422, f"Task {task_id}: review must contain an array of step records")
        fingerprint = digest(cleaned)
        definition = db.scalar(select(TaskDefinition).where(TaskDefinition.dataset_id == dataset.id,
                                                            TaskDefinition.task_id == task_id))
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
        revision = TaskRevision(task_definition_id=definition.id, revision=revision_number,
                                source_revision=fingerprint, content=cleaned)
        db.add(revision)
        db.flush()
        definition.current_revision_id = revision.id
        register_evidence(db, user, revision, None, cleaned)
    dataset.updated_at = utcnow()
    activity(db, user, "dataset.imported", "dataset", dataset.id, created=created, revised=revised, unchanged=unchanged)
    db.commit()
    return {"dataset_id": dataset.id, "created": created, "revised": revised, "unchanged": unchanged,
            "imported": created + revised + unchanged,
            "task_count": len(seen)}


async def _read_zip_request(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/zip":
        raise ZipDatasetError([{"path": "request", "message": "Send the ZIP as raw application/zip bytes",
                                "code": "unsupported_media_type"}])
    length = request.headers.get("content-length")
    if length:
        try:
            declared_size = int(length)
        except ValueError:
            raise ZipDatasetError([{"path": "request", "message": "Invalid Content-Length header",
                                    "code": "invalid_content_length"}]) from None
        if declared_size > MAX_ARCHIVE_BYTES:
            raise ZipDatasetError([{"path": "archive", "message": "ZIP archive exceeds the 32 MB limit",
                                    "code": "archive_too_large"}])
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_ARCHIVE_BYTES:
            raise ZipDatasetError([{"path": "archive", "message": "ZIP archive exceeds the 32 MB limit",
                                    "code": "archive_too_large"}])
        chunks.append(chunk)
    return b"".join(chunks)


def _zip_validation_http_error(exc: ZipDatasetError):
    return HTTPException(status_code=422, detail={"message": "ZIP dataset is invalid",
        "errors": exc.errors, "warnings": exc.warnings})


@app.post("/api/imports/zip/validate")
async def validate_dataset_zip(request: Request, user: User = Depends(require_role("admin", "manager"))):
    try:
        payload = await _read_zip_request(request)
        validated = validate_zip_dataset(payload)
    except ZipDatasetError as exc:
        raise _zip_validation_http_error(exc) from None
    return {"valid": True, "task_count": len(validated.tasks),
            "screenshot_count": len(set(path for paths in validated.assets_by_task.values() for path in paths)),
            "tasks": validated.summaries, "warnings": validated.warnings}


@app.post("/api/datasets/{dataset_id}/import-zip")
async def import_dataset_zip(dataset_id: str, request: Request,
                             db: Session = Depends(get_db), user: User = Depends(get_user)):
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
            definition = db.scalar(select(TaskDefinition).where(TaskDefinition.dataset_id == dataset.id,
                                                                TaskDefinition.task_id == task_id))
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
            revision = TaskRevision(task_definition_id=definition.id, revision=revision_number,
                                    source_revision=fingerprint, content=content)
            db.add(revision)
            db.flush()
            definition.current_revision_id = revision.id
            planned.append((task_id, revision, asset_paths))

        if planned:
            store = create_artifact_store(settings)
            for task_id, revision, asset_paths in planned:
                for relative_path in asset_paths:
                    image = validated.assets[relative_path]
                    sha = hashlib.sha256(image).hexdigest()
                    suffix = "." + relative_path.rsplit(".", 1)[-1].lower()
                    key = (f"workspaces/{dataset.workspace_id}/datasets/{dataset.id}/"
                           f"task-revisions/{revision.id}/assets/{sha}{suffix}")
                    object_key = store.put(key, image, IMAGE_TYPES[suffix])
                    db.add(StoredArtifact(workspace_id=dataset.workspace_id, task_revision_id=revision.id,
                        relative_path=relative_path, media_type=IMAGE_TYPES[suffix], object_key=object_key, sha256=sha))
        dataset.updated_at = utcnow()
        activity(db, user, "dataset.imported_zip", "dataset", dataset.id,
                 created=created, revised=revised, unchanged=unchanged)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Dataset changed during ZIP import; refresh and retry") from None
    except Exception:
        db.rollback()
        raise HTTPException(503, "ZIP import failed before database commit; no task revisions were committed") from None
    return {"dataset_id": dataset.id, "created": created, "revised": revised, "unchanged": unchanged,
            "imported": created + revised + unchanged, "task_count": len(validated.tasks),
            "warnings": validated.warnings}


@app.get("/api/datasets/{dataset_id}/sync-preview")
@app.post("/api/datasets/{dataset_id}/sync-preview")
def sync_preview(dataset_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    dataset = require_dataset_access(db, dataset_id, user, "manager")
    changes = []
    for definition in task_definitions(db, dataset.id):
        current = current_revision(db, definition)
        if current:
            changes.append({"task_id": definition.task_id, "revision_id": current.id,
                            "revision": current.revision, "source_revision": current.source_revision,
                            "content": current.content})
    return {"dataset_id": dataset.id, "new_task_revisions": changes, "count": len(changes)}


@app.get("/api/presets")
def presets(page: int = 1, per_page: int = 50, db: Session = Depends(get_db), user: User = Depends(get_user)):
    query = select(Preset).where(Preset.workspace_id == user.workspace_id,
                                 ~Preset.name.like("__run_config__%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.order_by(Preset.name).offset((page - 1) * per_page).limit(min(per_page, 200))).all()
    output = []
    for p in items:
        entry = record(p)
        revisions = db.scalars(select(PresetRevision).where(PresetRevision.preset_id == p.id).order_by(PresetRevision.revision)).all()
        entry["revisions"] = [record(r, omit=("configuration",)) | {"configuration": r.configuration, "preset_id": p.id} for r in revisions]
        entry["latest_revision"] = entry["revisions"][-1] if entry["revisions"] else None
        if entry["latest_revision"]:
            entry.update(entry["latest_revision"])
            entry["id"] = p.id
            entry["name"] = p.name
        output.append(entry)
    return {"items": output, "total": total}


@app.post("/api/presets")
def create_preset(body: PresetCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
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
    preset = db.scalar(select(Preset).where(Preset.workspace_id == user.workspace_id,
                                            Preset.name == body.name.strip()))
    if not preset:
        preset = Preset(workspace_id=user.workspace_id, name=body.name.strip(), created_by=user.id)
        db.add(preset)
        db.flush()
        revision_number = 1
    else:
        revision_number = (db.scalar(select(func.max(PresetRevision.revision)).where(PresetRevision.preset_id == preset.id)) or 0) + 1
    revision = PresetRevision(preset_id=preset.id, revision=revision_number, backend=body.backend, model=model,
                              reasoning=body.reasoning, budget_usd=body.budget_usd,
                              configuration=body.configuration, config_hash=digest(body.model_dump()), created_by=user.id)
    db.add(revision)
    activity(db, user, "preset.revision_created", "preset", preset.id, backend=body.backend, revision=revision_number)
    db.commit()
    return {**record(preset), **record(revision), "preset_id": preset.id,
            "id": preset.id, "name": preset.name, "revisions": [record(revision)]}


@app.get("/api/providers")
def providers(user: User = Depends(get_user)):
    try:
        from .review_backends import provider_capabilities
        values = provider_capabilities()
    except Exception:
        values = [{"id": "saved_replay", "name": "Saved POC replay", "available": True,
                   "configured": True, "capabilities": ["saved_result"]}]
    values = [{**item, "supported": bool(item.get("execution_enabled", item.get("available"))
                                               and item.get("id") in ("saved_replay", "model_api", "litellm",
                                                                       "claude_code", "codex", "gemini_cli"))}
              for item in values]
    if not any(item.get("id") == "litellm" for item in values):
        api = next((item for item in values if item.get("id") == "model_api"), None)
        if api:
            values.append({**api, "id": "litellm", "name": "LiteLLM API (alias)"})
    return {"default_backend": "saved_replay", "items": values, "backends": values, "providers": values}


PROVIDER_MODEL_BACKENDS = ("model_api", "litellm", "codex", "gemini_cli", "claude_code")
PROVIDER_MODEL_BACKEND_PATTERN = "^({})$".format("|".join(PROVIDER_MODEL_BACKENDS))


def provider_model_payload(snapshot: ProviderModelCatalog | None, backend: str) -> dict[str, Any]:
    if snapshot is None:
        return {"backend": backend, "models": [], "source": "not_discovered", "fetched_at": None,
                "status": "unknown", "note": "Provider model availability has not been checked."}
    return {"backend": snapshot.backend, "models": snapshot.models or [], "source": snapshot.source,
            "fetched_at": iso(snapshot.fetched_at), "status": snapshot.status, "note": snapshot.note}


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
            valid = item.provider == "openai" and (item.id.startswith("gpt-") or
                                                     (len(item.id) > 1 and item.id[0] == "o" and item.id[1].isdigit()))
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


@app.get("/api/providers/models")
def provider_models(backend: str = Query(..., pattern=PROVIDER_MODEL_BACKEND_PATTERN),
                    db: Session = Depends(get_db), user: User = Depends(get_user)):
    snapshot = db.get(ProviderModelCatalog, (user.workspace_id, backend))
    return provider_model_payload(snapshot, backend)


@app.post("/api/providers/models/sync")
def sync_provider_models(body: ProviderModelCatalogSync, db: Session = Depends(get_db),
                         user: User = Depends(require_role("admin"))):
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


@app.get("/api/batches")
def batches(page: int = 1, per_page: int = 50, include_archived: bool = False,
            db: Session = Depends(get_db), user: User = Depends(get_user)):
    query = select(Batch).where(Batch.workspace_id == user.workspace_id).order_by(Batch.created_at.desc())
    all_items = db.scalars(query).all()
    visible = []
    for batch in all_items:
        if not include_archived and is_archived(db, "run", batch.id):
            continue
        try:
            get_batch(db, batch.id, user)
            visible.append(batch)
        except HTTPException:
            pass
    start = max(page - 1, 0) * min(per_page, 200)
    return {"items": [batch_detail(db, b) for b in visible[start:start + min(per_page, 200)]], "total": len(visible)}


@app.post("/api/batches")
def create_batch(body: BatchCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager"))):
    dataset = db.get(Dataset, body.dataset_id)
    preset = db.get(Preset, body.preset_id)
    if not dataset or dataset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Dataset not found")
    if not preset or preset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Preset not found")
    preset_revision = db.scalar(select(PresetRevision).where(PresetRevision.preset_id == preset.id).order_by(PresetRevision.revision.desc()))
    if not preset_revision:
        raise HTTPException(409, "Preset has no immutable revision")
    definitions = {d.task_id: d for d in task_definitions(db, dataset.id)}
    selected = body.task_ids if body.task_ids is not None else list(definitions)
    if len(set(selected)) != len(selected):
        raise HTTPException(422, "task_ids must be unique")
    unknown = sorted(set(selected) - set(definitions))
    if unknown:
        raise HTTPException(404, f"Unknown task IDs: {', '.join(unknown[:5])}")
    release = current_release(db, user.workspace_id)
    batch = Batch(workspace_id=user.workspace_id, dataset_id=dataset.id, name=body.name.strip(),
                  description=body.description, mode=body.mode, preset_revision_id=preset_revision.id,
                  taxonomy_release_id=release.id if release else None,
                  status="draft", created_by=user.id)
    db.add(batch)
    db.flush()
    wave = SyncWave(batch_id=batch.id, number=1, sync_key="initial", task_count=len(selected), created_by=user.id)
    db.add(wave)
    db.flush()
    for task_id in selected:
        definition = definitions[task_id]
        revision = current_revision(db, definition)
        if revision:
            add_member(db, batch, definition, revision, wave.id, user)
    for team_id in body.team_ids:
        team = db.get(Team, team_id)
        if not team or team.workspace_id != user.workspace_id:
            raise HTTPException(404, "Team not found")
        db.add(BatchGrant(batch_id=batch.id, team_id=team.id, role="reviewer", created_by=user.id))
    activity(db, user, "batch.created", "batch", batch.id, member_count=len(selected), mode=batch.mode)
    db.commit()
    return batch_detail(db, batch)


def create_run_records(db: Session, user: User, *, name: str, description: str,
                       datasets: list[Dataset], members: list[tuple[TaskDefinition, TaskRevision]],
                       workflow: dict[str, Any], execution: dict[str, Any],
                       team_ids: list[str] | None = None, user_ids: list[str] | None = None,
                       rerun_of: str | None = None) -> Batch:
    preset_revision = create_run_preset(db, user, execution)
    batch = Batch(workspace_id=user.workspace_id, dataset_id=datasets[0].id, name=name.strip(),
        description=description, mode="fixed", preset_revision_id=preset_revision.id,
        taxonomy_release_id=(current_release(db, user.workspace_id).id if current_release(db, user.workspace_id) else None),
        status="draft", created_by=user.id)
    db.add(batch)
    db.flush()
    for position, dataset in enumerate(datasets):
        db.add(RunSource(batch_id=batch.id, dataset_id=dataset.id, position=position))
    config = RunConfiguration(batch_id=batch.id, workflow_revision_id=workflow["revision_id"],
        workflow_snapshot=copy.deepcopy(workflow), execution_snapshot=copy.deepcopy(execution),
        rerun_of_batch_id=rerun_of)
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


@app.post("/api/runs")
def create_run(body: RunCreate, db: Session = Depends(get_db), user: User = Depends(get_user)):
    if bool(body.dataset_ids) == bool(body.task_definition_ids):
        raise HTTPException(422, "Choose exactly one of dataset_ids or task_definition_ids")
    if body.dataset_ids and len(set(body.dataset_ids)) != len(body.dataset_ids):
        raise HTTPException(422, "dataset_ids must be unique")
    if body.task_definition_ids and len(set(body.task_definition_ids)) != len(body.task_definition_ids):
        raise HTTPException(422, "task_definition_ids must be unique")
    workflow = workflow_by_revision(body.workflow_revision_id)
    if body.dataset_ids:
        datasets_selected = [require_dataset_access(db, dataset_id, user, "manager") for dataset_id in body.dataset_ids]
        definitions = [definition for dataset in datasets_selected for definition in task_definitions(db, dataset.id)
                       if not is_archived(db, "task", definition.id)]
    else:
        definitions = []
        for definition_id in body.task_definition_ids or []:
            definition = db.get(TaskDefinition, definition_id)
            if not definition:
                raise HTTPException(404, "Task definition not found")
            require_dataset_access(db, definition.dataset_id, user, "manager")
            if is_archived(db, "task", definition.id):
                raise HTTPException(409, "Archived tasks cannot be added to a run")
            definitions.append(definition)
    if not definitions:
        raise HTTPException(422, "Run selection contains no active tasks")
    datasets_by_id: dict[str, Dataset] = {}
    selected_members = []
    for definition in definitions:
        dataset = db.get(Dataset, definition.dataset_id)
        if not dataset:
            continue
        datasets_by_id[dataset.id] = dataset
        revision = current_revision(db, definition)
        if revision:
            selected_members.append((definition, revision))
    if not selected_members:
        raise HTTPException(422, "Run selection contains no task revisions")
    execution = execution_snapshot(body.execution.model_dump(), workflow)
    batch = create_run_records(db, user, name=body.name, description=body.description,
        datasets=list(datasets_by_id.values()), members=selected_members, workflow=workflow,
        execution=execution, team_ids=body.team_ids, user_ids=body.user_ids)
    activity(db, user, "run.created", "run", batch.id, task_count=len(selected_members),
             dataset_count=len(datasets_by_id), workflow_revision_id=workflow["revision_id"])
    db.commit()
    return run_detail(db, batch, user)


@app.get("/api/runs")
def list_runs(page: int = 1, per_page: int = 50, include_archived: bool = False,
              db: Session = Depends(get_db), user: User = Depends(get_user)):
    rows = db.scalars(select(Batch).where(Batch.workspace_id == user.workspace_id)
                      .order_by(Batch.created_at.desc())).all()
    visible = []
    for batch in rows:
        if not include_archived and is_archived(db, "run", batch.id):
            continue
        try:
            get_batch(db, batch.id, user)
            visible.append(batch)
        except HTTPException:
            continue
    size = min(max(per_page, 1), 200)
    start = max(page - 1, 0) * size
    return {"items": [run_detail(db, item, user) for item in visible[start:start + size]], "total": len(visible)}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, _role = get_batch(db, run_id, user)
    if is_archived(db, "run", run_id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return run_detail(db, batch, user)


@app.post("/api/runs/{run_id}/configure")
def configure_run(run_id: str, body: RunConfigure, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    if batch.status != "draft" or db.scalar(select(func.count(Job.id)).where(Job.batch_id == batch.id)):
        raise HTTPException(409, "Run configuration is frozen after start")
    current_config = db.scalar(select(RunConfiguration).where(RunConfiguration.batch_id == batch.id))
    workflow = workflow_by_revision(body.workflow_revision_id or
        (current_config.workflow_revision_id if current_config else "trajectory_review@1"))
    pinned = db.get(PresetRevision, batch.preset_revision_id)
    current_execution = (current_config.execution_snapshot if current_config else {
        "backend": pinned.backend, "model": pinned.model, "reasoning": pinned.reasoning,
        "budget_usd": pinned.budget_usd, "configuration": pinned.configuration}) if pinned else {}
    requested_execution = body.execution.model_dump() if body.execution else current_execution
    if "workflow_snapshot" in (requested_execution.get("configuration") or {}):
        requested_execution["configuration"] = {key: value for key, value in requested_execution["configuration"].items()
            if key != "workflow_snapshot"}
    execution = execution_snapshot(requested_execution, workflow)
    new_revision = create_run_preset(db, user, execution)
    batch.preset_revision_id = new_revision.id
    if not current_config:
        current_config = RunConfiguration(batch_id=batch.id, workflow_revision_id=workflow["revision_id"],
            workflow_snapshot=workflow, execution_snapshot=execution, revision=1)
        db.add(current_config)
    else:
        current_config.workflow_revision_id = workflow["revision_id"]
        current_config.workflow_snapshot = workflow
        current_config.execution_snapshot = execution
        current_config.revision += 1
    activity(db, user, "run.configured", "run", batch.id, workflow_revision_id=workflow["revision_id"])
    db.commit()
    return run_detail(db, batch, user)


@app.post("/api/runs/{run_id}/start")
def start_run(run_id: str, body: StartBatch | None = None,
              db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Cancelled runs cannot be restarted; create a rerun")
    if batch.status == "paused":
        raise HTTPException(409, "Resume the paused run instead of starting it again")
    preset = db.get(PresetRevision, batch.preset_revision_id)
    if not preset:
        raise HTTPException(409, "Pinned execution snapshot is missing")
    require_preset_budget_confirmation(preset, body)
    added = _enqueue_review_jobs(db, batch, user)
    batch.status = batch_execution_status(db, batch)
    batch.updated_at = utcnow()
    activity(db, user, "run.started", "run", batch.id, jobs_added=added,
             backend=preset.backend, budget_usd=preset.budget_usd)
    db.commit()
    return {**run_detail(db, batch, user), "jobs_added": added}


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    cancel_batch(run_id, db, (batch, user, role))
    return run_detail(db, batch, user)


@app.post("/api/runs/{run_id}/pause")
def pause_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    pause_batch(run_id, db, (batch, user, role))
    return run_detail(db, batch, user)


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    resume_batch(run_id, db, (batch, user, role))
    return run_detail(db, batch, user)


@app.post("/api/runs/{run_id}/sync")
def sync_run(run_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", batch.id):
        raise HTTPException(404, "Run not found")
    result = sync_batch(run_id, request, db, (batch, user, role))
    return {**result, "run_id": run_id}


@app.get("/api/runs/{run_id}/tasks")
def run_tasks(run_id: str, page: int = 1, per_page: int = 100, include_archived: bool = False,
              db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, _role = get_batch(db, run_id, user)
    if is_archived(db, "run", batch.id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return batch_tasks(run_id, page, per_page, db, (batch, user, _role))


@app.get("/api/runs/{run_id}/tasks/{task_id}")
def get_run_task(run_id: str, task_id: str, member_id: str | None = None, include_archived: bool = False,
                 db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, _role = get_batch(db, run_id, user)
    if is_archived(db, "run", batch.id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return get_batch_task(run_id, task_id, member_id, db, (batch, user, _role))


@app.post("/api/runs/{run_id}/archive")
def archive_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    return set_archived(db, user, "run", batch.id, True)


@app.post("/api/runs/{run_id}/restore")
def restore_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    batch, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    return set_archived(db, user, "run", batch.id, False)


@app.post("/api/runs/{run_id}/rerun")
def rerun_run(run_id: str, body: RunRerun | None = None,
              db: Session = Depends(get_db), user: User = Depends(get_user)):
    source, role = get_batch(db, run_id, user, required_role="manager")
    need_batch_manager(role)
    if is_archived(db, "run", source.id):
        raise HTTPException(409, "Archived runs cannot be rerun")
    body = body or RunRerun()
    current_config = db.scalar(select(RunConfiguration).where(RunConfiguration.batch_id == source.id))
    source_preset = db.get(PresetRevision, source.preset_revision_id)
    if not source_preset:
        raise HTTPException(409, "Source run execution snapshot is missing")
    source_workflow_id = current_config.workflow_revision_id if current_config else "trajectory_review@1"
    workflow = workflow_by_revision(body.workflow_revision_id or source_workflow_id)
    source_execution = current_config.execution_snapshot if current_config else {
        "backend": source_preset.backend, "model": source_preset.model, "reasoning": source_preset.reasoning,
        "budget_usd": source_preset.budget_usd, "configuration": source_preset.configuration}
    if "workflow_snapshot" in (source_execution.get("configuration") or {}):
        source_execution = copy.deepcopy(source_execution)
        source_execution["configuration"] = {key: value for key, value in source_execution["configuration"].items()
                                              if key != "workflow_snapshot"}
    execution = execution_snapshot(body.execution.model_dump() if body.execution else source_execution, workflow)
    sources = list(db.scalars(select(RunSource.dataset_id).where(RunSource.batch_id == source.id)
                              .order_by(RunSource.position)).all()) or [source.dataset_id]
    datasets_selected = [require_dataset_access(db, dataset_id, user, "manager") for dataset_id in sources]
    members = db.scalars(select(BatchMember).where(BatchMember.batch_id == source.id).order_by(BatchMember.created_at)).all()
    selected = []
    for member in members:
        definition, revision = db.get(TaskDefinition, member.task_definition_id), db.get(TaskRevision, member.task_revision_id)
        if definition and revision:
            selected.append((definition, revision))
    if not selected:
        raise HTTPException(422, "Source run has no task revisions to rerun")
    grants = db.scalars(select(BatchGrant).where(BatchGrant.batch_id == source.id)).all()
    team_ids = [grant.team_id for grant in grants if grant.team_id]
    user_ids = [grant.user_id for grant in grants if grant.user_id]
    new_run = create_run_records(db, user, name=body.name or f"Rerun: {source.name}",
        description=source.description, datasets=datasets_selected, members=selected,
        workflow=workflow, execution=execution, team_ids=team_ids, user_ids=user_ids, rerun_of=source.id)
    activity(db, user, "run.rerun_created", "run", new_run.id, source_run_id=source.id)
    db.commit()
    return run_detail(db, new_run, user)


@app.get("/api/batches/{batch_id}")
def get_batch_detail(batch_id: str, include_archived: bool = False,
                     db: Session = Depends(get_db), access=Depends(require_batch())):
    batch, user, _role = access
    if is_archived(db, "run", batch.id) and not include_archived:
        raise HTTPException(404, "Run not found")
    return batch_detail(db, db.get(Batch, batch.id))


@app.get("/api/batches/{batch_id}/tasks")
def batch_tasks(batch_id: str, page: int = 1, per_page: int = 100,
                db: Session = Depends(get_db), access=Depends(require_batch())):
    batch, user, _role = access
    query = select(BatchMember).where(BatchMember.batch_id == batch.id).order_by(BatchMember.created_at, BatchMember.task_id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    members = db.scalars(query.offset((page - 1) * min(per_page, 500)).limit(min(per_page, 500))).all()
    items = []
    for member in members:
        revision = db.get(TaskRevision, member.task_revision_id)
        if revision:
            items.append(task_view(db, revision.content, revision.id, member.task_id, revision.revision,
                                   member, member_review(db, member)))
    return {"items": items, "total": total}


@app.get("/api/batches/{batch_id}/tasks/{task_id}")
def get_batch_task(batch_id: str, task_id: str, member_id: str | None = None,
                   db: Session = Depends(get_db), access=Depends(require_batch())):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    revision = db.get(TaskRevision, member.task_revision_id)
    task = task_view(db, revision.content, revision.id, task_id, revision.revision,
                     member, member_review(db, member))
    feedback = db.scalars(select(TaskFeedback).where(TaskFeedback.member_id == member.id)
                          .order_by(TaskFeedback.created_at)).all()
    return {**task, "member": {"id": member.id, "batch_id": batch.id, "task_id": task_id,
                               "status": member.status, "processing_status": member.status,
                               "review_kind": member.review_kind},
            "task": task, "review": task.get("review"), "review_history": task.get("review_history", []),
            "feedback": [record(item) for item in feedback]}


@app.post("/api/batches/{batch_id}/sync")
def sync_batch(batch_id: str, request: Request, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    if batch.mode != "appendable":
        raise HTTPException(409, "Fixed batches cannot append tasks")
    key = request.headers.get("Idempotency-Key") or request.query_params.get("sync_key")
    if not key:
        latest_ids = [(d.task_id, current_revision(db, d).id if current_revision(db, d) else None)
                      for d in task_definitions(db, batch.dataset_id)]
        key = "snapshot-" + digest(latest_ids)
    if len(key) > 200:
        raise HTTPException(422, "Sync key too long")
    old = db.scalar(select(SyncWave).where(SyncWave.batch_id == batch.id, SyncWave.sync_key == key))
    if old:
        return {"wave": record(old), "added": 0, "idempotent_replay": True}
    existing = set(db.scalars(select(BatchMember.task_revision_id).where(BatchMember.batch_id == batch.id)).all())
    definitions = task_definitions(db, batch.dataset_id)
    new = [(d, current_revision(db, d)) for d in definitions]
    new = [(d, r) for d, r in new if r and r.id not in existing]
    wave_number = (db.scalar(select(func.max(SyncWave.number)).where(SyncWave.batch_id == batch.id)) or 0) + 1
    wave = SyncWave(batch_id=batch.id, number=wave_number, sync_key=key, task_count=len(new), created_by=user.id)
    db.add(wave)
    db.flush()
    for definition, revision in new:
        add_member(db, batch, definition, revision, wave.id, user)
    batch.updated_at = utcnow()
    activity(db, user, "batch.synced", "batch", batch.id, wave_number=wave_number, added=len(new), sync_key=key)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Concurrent duplicate delivery resolves to the already committed immutable wave.
        old = db.scalar(select(SyncWave).where(SyncWave.batch_id == batch.id, SyncWave.sync_key == key))
        if old:
            return {"wave": record(old), "added": 0, "idempotent_replay": True}
        raise HTTPException(409, "Concurrent sync conflict; retry with the same key")
    return {"wave": record(wave), "added": len(new), "idempotent_replay": False}


@app.post("/api/batches/{batch_id}/grants")
@app.post("/api/runs/{batch_id}/grants")
def create_batch_grant(batch_id: str, body: BatchGrantCreate, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    if bool(body.team_id) == bool(body.user_id):
        raise HTTPException(422, "Provide exactly one of team_id or user_id")
    if body.team_id:
        target = db.get(Team, body.team_id)
        if not target or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "Team not found")
    else:
        target = db.get(User, body.user_id)
        if not target or target.workspace_id != user.workspace_id:
            raise HTTPException(404, "User not found")
    grant = BatchGrant(batch_id=batch.id, team_id=body.team_id, user_id=body.user_id,
                       role=body.role, created_by=user.id)
    db.add(grant)
    activity(db, user, "batch.grant_created", "batch", batch.id, grant_role=body.role,
             team_id=body.team_id, user_id=body.user_id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        grant = db.scalar(select(BatchGrant).where(BatchGrant.batch_id == batch.id,
            BatchGrant.team_id == body.team_id if body.team_id else BatchGrant.team_id.is_(None),
            BatchGrant.user_id == body.user_id if body.user_id else BatchGrant.user_id.is_(None),
            BatchGrant.role == body.role))
    return record(grant)


@app.delete("/api/batches/{batch_id}/grants/{grant_id}", status_code=204)
@app.delete("/api/runs/{batch_id}/grants/{grant_id}", status_code=204)
def delete_batch_grant(batch_id: str, grant_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    grant = db.get(BatchGrant, grant_id)
    if not grant or grant.batch_id != batch.id:
        raise HTTPException(404, "Grant not found")
    db.delete(grant)
    activity(db, user, "batch.grant_revoked", "batch", batch.id, grant_id=grant_id)
    db.commit()


def _enqueue_review_jobs(db: Session, batch: Batch, user: User):
    preset_revision = db.get(PresetRevision, batch.preset_revision_id)
    if not preset_revision:
        raise HTTPException(409, "Pinned preset revision is missing")
    members = db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id)).all()
    shared_labels = []
    release = db.get(TaxonomyRelease, batch.taxonomy_release_id) if batch.taxonomy_release_id else None
    if release:
        shared_labels.extend(copy.deepcopy((release.content or {}).get("labels", [])))
    known = {str(item.get("id")) for item in shared_labels if isinstance(item, dict) and item.get("id")}
    proposals = db.scalars(select(TaxonomyProposal).where(TaxonomyProposal.workspace_id == batch.workspace_id)
                           .order_by(TaxonomyProposal.created_at)).all()
    for proposal in proposals:
        revision = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if not revision:
            continue
        label_id = proposal.label_id or f"draft:{proposal.id}"
        if str(label_id) in known:
            continue
        shared_labels.append({"id": label_id, "name": revision.name,
                              "description": revision.description, "status": "draft"})
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
        old = db.scalar(select(Job).where(Job.idempotency_key == idem))
        if old:
            continue
        job = Job(workspace_id=user.workspace_id, batch_id=batch.id, member_id=member.id,
                  stage="review", review_kind=route, preset_revision_id=preset_revision.id,
                  idempotency_key=idem, generation=1, fence_token=0, status="queued",
                  max_attempts=min(4, max(1, int(settings.max_job_attempts))),
                  shared_labels_snapshot=copy.deepcopy(shared_labels))
        db.add(job)
        db.flush()
        db.add(OutboxEvent(job_id=job.id, generation=job.generation, status="pending"))
        member.status = "queued"
        added += 1
    return added


def require_preset_budget_confirmation(preset: PresetRevision, body: StartBatch | None):
    if preset.backend == "saved_replay":
        return
    if os.getenv("ALLOW_HOSTED_INFERENCE", "false").lower() != "true":
        raise HTTPException(409, "Hosted inference is disabled. Set ALLOW_HOSTED_INFERENCE=true to opt in.")
    from .review_backends import provider_capabilities
    capability_id = "model_api" if preset.backend == "litellm" else preset.backend
    capability = next((item for item in provider_capabilities() if item.get("id") == capability_id), None)
    if not capability or not capability.get("configured") or capability.get("execution_enabled") is False:
        raise HTTPException(409, "This backend is not configured and enabled on the local worker")
    if not body or not body.confirm_budget or body.expected_budget_usd != preset.budget_usd:
        raise HTTPException(409, "Confirm the pinned batch budget before starting")


def batch_execution_status(db: Session, batch: Batch) -> str:
    if batch.status in ("paused", "cancelled"):
        return batch.status
    active_jobs = db.scalar(select(func.count(Job.id)).where(
        Job.batch_id == batch.id, Job.status.in_(("queued", "running", "retrying")))) or 0
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
    return db.scalars(select(Batch).where(Batch.id == batch.id).with_for_update()
                      .execution_options(populate_existing=True)).first() or batch


@app.post("/api/batches/{batch_id}/start")
def start_batch(batch_id: str, body: StartBatch | None = None, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Cancelled batches cannot be restarted")
    if batch.status == "paused":
        raise HTTPException(409, "Resume the paused batch instead of starting it again")
    preset = db.get(PresetRevision, batch.preset_revision_id)
    if not preset:
        raise HTTPException(409, "Pinned preset revision is missing")
    require_preset_budget_confirmation(preset, body)
    added = _enqueue_review_jobs(db, batch, user)
    batch.status = batch_execution_status(db, batch)
    batch.updated_at = utcnow()
    activity(db, user, "batch.started", "batch", batch.id, jobs_added=added,
             backend=preset.backend, budget_usd=preset.budget_usd)
    db.commit()
    return {**batch_detail(db, batch), "jobs_added": added}


@app.post("/api/batches/{batch_id}/pause")
def pause_batch(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status != "running":
        raise HTTPException(409, "Only a running batch can be paused")
    batch.status = "paused"
    batch.updated_at = utcnow()
    # Jobs that have not been delivered stay queued; outbox relay skips paused batches.
    activity(db, user, "batch.paused", "batch", batch.id)
    db.commit()
    return batch_detail(db, batch)


@app.post("/api/batches/{batch_id}/resume")
def resume_batch(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Cancelled batches cannot be resumed")
    if batch.status not in ("paused", "running"):
        raise HTTPException(409, "Only a paused batch can be resumed")
    batch.status = "running"
    batch.updated_at = utcnow()
    for job in db.scalars(select(Job).where(Job.batch_id == batch.id,
            Job.status.in_(("queued", "retrying")))).all():
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job.id,
            OutboxEvent.generation == job.generation))
        if not event:
            event = OutboxEvent(job_id=job.id, generation=job.generation, status="pending")
            db.add(event)
        else:
            event.status = "pending"
        event.available_at = utcnow()
        job.available_at = utcnow()
        event.relay_owner = None
        event.relay_lease_expires_at = None
        event.sent_at = None
        event.last_error = None
    batch.status = batch_execution_status(db, batch)
    activity(db, user, "batch.resumed", "batch", batch.id)
    db.commit()
    return batch_detail(db, batch)


@app.post("/api/batches/{batch_id}/reconcile")
@app.post("/api/runs/{batch_id}/reconcile")
def reconcile_batch_status(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    """Explicitly repair a stale running status when persisted work is terminal."""
    batch, user, role = access
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    previous = batch.status
    derived = batch_execution_status(db, batch)
    if previous != "running" or derived not in ("completed", "awaiting_review"):
        return {**batch_detail(db, batch), "reconciled": False,
                "reconcile_reason": f"Stored status is {previous}; authoritative work state is {derived}."}
    batch.status = derived
    batch.updated_at = utcnow()
    activity(db, user, "batch.status_reconciled", "batch", batch.id,
             previous_status=previous, status=derived)
    db.commit()
    return {**batch_detail(db, batch), "reconciled": True, "previous_status": previous}


@app.post("/api/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str, db: Session = Depends(get_db), access=Depends(require_batch("manager"))):
    batch, user, role = access
    need_batch_manager(role)
    # Workers lock their job before the batch row. Keep the same order here so a
    # cancellation cannot deadlock with a worker committing its final result.
    jobs = db.scalars(select(Job).where(Job.batch_id == batch.id).order_by(Job.id)
                      .with_for_update().execution_options(populate_existing=True)).all()
    batch = lock_batch_status(db, batch)
    if batch.status == "completed":
        raise HTTPException(409, "Completed batches cannot be cancelled")
    if batch.status == "cancelled":
        return batch_detail(db, batch)
    batch.status = "cancelled"
    batch.updated_at = utcnow()
    now = utcnow()
    cancelled_jobs = 0
    for job in jobs:
        if job.status not in ("queued", "running", "retrying"):
            continue
        old_generation, old_fence = job.generation, job.fence_token
        was_running = job.status == "running"
        job.status = "cancelled"
        job.generation += 1
        job.fence_token += 1
        job.updated_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.error = ("Cancelled while active; completion and provider usage are unknown."
                     if was_running else "Cancelled before dispatch.")
        if was_running:
            job.usage = {"kind": "unknown", "estimated_usd": None}
            job.cost_usd = None
            attempt = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id,
                JobAttempt.generation == old_generation, JobAttempt.fence_token == old_fence,
                JobAttempt.status == "running").with_for_update())
            if attempt:
                attempt.status = "cancelled"
                attempt.error = job.error
                attempt.usage = {"kind": "unknown", "estimated_usd": None}
                attempt.cost_usd = None
                attempt.finished_at = now
        member = db.get(BatchMember, job.member_id)
        if member:
            member.status = "cancelled"
        for event in db.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job.id,
                OutboxEvent.generation == old_generation, OutboxEvent.status.in_(("pending", "sending")))):
            event.status = "cancelled"
        cancelled_jobs += 1
    cancelled_members = 0
    for member in db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id,
            BatchMember.status.not_in(("completed", "failed", "cancelled")))):
        member.status = "cancelled"
        cancelled_members += 1
    activity(db, user, "batch.cancelled", "batch", batch.id, cancelled_jobs=cancelled_jobs,
             cancelled_members=cancelled_members)
    db.commit()
    return batch_detail(db, batch)


@app.get("/api/jobs")
def jobs(page: int = 1, per_page: int = 100, db: Session = Depends(get_db), user: User = Depends(get_user)):
    query = select(Job).where(Job.workspace_id == user.workspace_id)
    if user.role not in ("admin", "manager"):
        batch_ids = visible_batch_ids(db, user)
        query = query.where(Job.batch_id.in_(batch_ids)) if batch_ids else query.where(False)
    query = query.order_by(Job.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.offset((page - 1) * min(per_page, 500)).limit(min(per_page, 500))).all()
    output = []
    for job in items:
        item = job_detail(db, job)
        member = db.get(BatchMember, job.member_id)
        revision = db.get(TaskRevision, member.task_revision_id) if member else None
        item["task_id"] = member.task_id if member else None
        item["task_title"] = revision.content.get("title") if revision else None
        item["outcome"] = (revision.content or {}).get("outcome") if revision else None
        item["score"] = (revision.content or {}).get("score") if revision else None
        item["run_id"] = job.batch_id
        item["attempt"] = job.attempt_count
        output.append(item)
    return {"items": output, "total": total}


@app.get("/api/jobs/{job_id}")
def job_by_id(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    job = db.get(Job, job_id)
    if not job or job.workspace_id != user.workspace_id:
        raise HTTPException(404, "Job not found")
    batch, _role = get_batch(db, job.batch_id, user)
    item = job_detail(db, job)
    member = db.get(BatchMember, job.member_id)
    revision = db.get(TaskRevision, member.task_revision_id) if member else None
    item.update({"run_id": batch.id, "run_name": batch.name,
        "task_id": member.task_id if member else None,
        "task_title": (revision.content or {}).get("title") if revision else None,
        "outcome": (revision.content or {}).get("outcome") if revision else None,
        "score": (revision.content or {}).get("score") if revision else None,
        "member_id": member.id if member else None})
    return item


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, body: StartBatch | None = None, db: Session = Depends(get_db), user: User = Depends(get_user)):
    job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()
                     .execution_options(populate_existing=True)).first()
    if not job or job.workspace_id != user.workspace_id:
        raise HTTPException(404, "Job not found")
    batch, role = get_batch(db, job.batch_id, user, required_role="manager")
    need_batch_manager(role)
    batch = lock_batch_status(db, batch)
    if batch.status == "cancelled":
        raise HTTPException(409, "Jobs in a cancelled batch cannot be retried")
    preset = db.get(PresetRevision, job.preset_revision_id)
    if not preset:
        raise HTTPException(409, "Pinned preset revision is missing")
    require_preset_budget_confirmation(preset, body)
    if job.status not in ("failed", "completed"):
        raise HTTPException(409, "Only failed or completed jobs can be retried")
    if job.attempt_count >= job.max_attempts:
        raise HTTPException(409, "Bounded retry limit has been reached")
    job.generation += 1
    job.fence_token += 1
    job.status = "queued"
    job.error = None
    job.lease_owner = None
    job.lease_expires_at = None
    job.available_at = utcnow()
    job.updated_at = utcnow()
    job.idempotency_key = f"review:{job.member_id}:{job.preset_revision_id}:{job.generation}"
    db.add(OutboxEvent(job_id=job.id, generation=job.generation, status="pending"))
    member = db.get(BatchMember, job.member_id)
    if member:
        member.status = "queued"
    if batch.status != "paused":
        batch.status = "running"
    batch.updated_at = utcnow()
    activity(db, user, "job.retried", "job", job.id, generation=job.generation)
    db.commit()
    return record(job)


@app.get("/api/activity")
def activity_list(page: int = 1, per_page: int = 100, db: Session = Depends(get_db), user: User = Depends(get_user)):
    query = select(ActivityEvent).where(ActivityEvent.workspace_id == user.workspace_id)
    if user.role not in ("admin", "manager"):
        query = query.where(ActivityEvent.actor_id == user.id)
    query = query.order_by(ActivityEvent.created_at.desc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(query.offset((page - 1) * min(per_page, 500)).limit(min(per_page, 500))).all()
    return {"items": [record(item) for item in items], "total": total}


def current_release(db: Session, workspace_id: str) -> TaxonomyRelease | None:
    return db.scalar(select(TaxonomyRelease).where(TaxonomyRelease.workspace_id == workspace_id).order_by(TaxonomyRelease.created_at.desc()).limit(1))


def proposal_view(db: Session, proposal: TaxonomyProposal) -> dict[str, Any]:
    item = record(proposal)
    revision = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
    revisions = db.scalars(select(ProposalRevision).where(ProposalRevision.proposal_id == proposal.id)
                            .order_by(ProposalRevision.revision)).all()
    item["revisions"] = [record(r) for r in revisions]
    item["latest_revision"] = record(revision) if revision else None
    if revision:
        item.update({"name": revision.name, "description": revision.description,
                     "evidence_refs": revision.evidence_refs, "revision": revision.revision,
                     "status": "draft"})
    item["feedback"] = [record(f) for f in db.scalars(select(ProposalFeedback).where(ProposalFeedback.proposal_id == proposal.id).order_by(ProposalFeedback.created_at)).all()]
    return item


def candidate_view(candidate: TaxonomyCandidate) -> dict[str, Any]:
    item = record(candidate)
    content = candidate.content or {}
    item["hash"] = candidate.content_hash
    item["labels"] = copy.deepcopy(content.get("labels", []))
    item["mappings"] = copy.deepcopy(content.get("mappings", []))
    item["unresolved"] = copy.deepcopy(content.get("unresolved", []))
    item["curation"] = copy.deepcopy(content.get("curation"))
    item["status"] = "pending review"
    db = object_session(candidate)
    if db:
        decisions = db.scalars(select(CandidateDecision).where(CandidateDecision.candidate_id == candidate.id)).all()
        item["decisions"] = [record(decision) for decision in decisions]
        if any(decision.action == "approve" for decision in decisions):
            item["status"] = "approved"
        elif any(decision.action == "reject" for decision in decisions):
            item["status"] = "rejected"
        else:
            latest = current_release(db, candidate.workspace_id)
            heads, _ = _taxonomy_proposal_snapshot(db, candidate.workspace_id)
            item["stale"] = (candidate.base_hash != (latest.content_hash if latest else digest({"labels": []})) or
                             candidate.proposal_heads != heads)
            if item["stale"]:
                item["status"] = "stale"
    return item


def _taxonomy_proposal_snapshot(db: Session, workspace_id: str):
    heads: dict[str, str] = {}
    entries = []
    proposals = db.scalars(select(TaxonomyProposal).where(TaxonomyProposal.workspace_id == workspace_id)
                           .order_by(TaxonomyProposal.created_at)).all()
    for proposal in proposals:
        rev = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if not rev:
            continue
        head = {"revision_hash": rev.content_hash, "base_hash": proposal.base_hash,
                "base_release_id": proposal.base_release_id, "kind": proposal.kind,
                "label_id": proposal.label_id}
        heads[proposal.id] = digest(head)
        feedback = db.scalars(select(ProposalFeedback).where(ProposalFeedback.proposal_id == proposal.id)
                              .order_by(ProposalFeedback.created_at)).all()
        entries.append({"proposal_id": proposal.id, "kind": proposal.kind, "label_id": proposal.label_id,
                        "name": rev.name, "description": rev.description,
                        "evidence_refs": rev.evidence_refs, "base_hash": proposal.base_hash,
                        "base_release_id": proposal.base_release_id,
                        "feedback": [item.text for item in feedback]})
    return heads, entries


def _curate_taxonomy(db: Session, user: User, body: TaxonomyConsolidate):
    if not body.confirm_budget or body.expected_budget_usd is None:
        raise HTTPException(409, "Confirm the pinned taxonomy curation budget before starting")
    preset_revision = db.get(PresetRevision, body.preset_revision_id)
    preset = db.get(Preset, preset_revision.preset_id) if preset_revision else None
    if not preset_revision or not preset or preset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Taxonomy curation preset revision not found")
    if body.expected_budget_usd != preset_revision.budget_usd:
        raise HTTPException(409, "Confirmed budget does not match the pinned curation preset")
    if os.getenv("ALLOW_HOSTED_INFERENCE", "false").lower() != "true":
        raise HTTPException(409, "Hosted inference is disabled. Set ALLOW_HOSTED_INFERENCE=true to opt in.")

    lock_taxonomy_workspace(db, user.workspace_id)
    release = current_release(db, user.workspace_id)
    base_content = copy.deepcopy(release.content if release else {"labels": []})
    base_hash = release.content_hash if release else digest(base_content)
    base_release_id = release.id if release else None
    heads, proposals = _taxonomy_proposal_snapshot(db, user.workspace_id)
    if not proposals:
        raise HTTPException(409, "Add at least one taxonomy proposal before paid curation")
    preset_record = record(preset_revision)
    # Release the workspace advisory transaction lock before any provider request.
    db.commit()

    from .review_backends import ReviewBackendError
    from .taxonomy_backend import consolidate_drafts
    try:
        result = consolidate_drafts(preset_revision=preset_record, base_content=base_content,
                                    proposals=proposals)
    except ReviewBackendError as exc:
        usage = copy.deepcopy(exc.usage) if isinstance(exc.usage, dict) else {"kind": "unknown", "estimated_usd": None}
        activity(db, user, "taxonomy.curation_failed", "taxonomy", None,
                 preset_revision_id=preset_revision.id, usage=usage)
        db.commit()
        raise HTTPException(422, str(exc)) from None

    # The provider call ran outside the database transaction's lock. Discard its result if
    # either the immutable release or any draft head moved while it was in flight.
    lock_taxonomy_workspace(db, user.workspace_id)
    db.expire_all()
    latest = current_release(db, user.workspace_id)
    latest_hash = latest.content_hash if latest else digest({"labels": []})
    latest_heads, _ = _taxonomy_proposal_snapshot(db, user.workspace_id)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {"kind": "unknown", "estimated_usd": None}
    if ((latest.id if latest else None) != base_release_id or latest_hash != base_hash or latest_heads != heads):
        activity(db, user, "taxonomy.curation_discarded_stale", "taxonomy", None,
                 preset_revision_id=preset_revision.id, usage=usage)
        db.commit()
        raise HTTPException(409, "Taxonomy changed during curation; the paid draft was discarded")

    content = result.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("labels"), list):
        raise HTTPException(422, "Taxonomy curation returned an invalid candidate")
    content = copy.deepcopy(content)
    content["curation"] = {"preset_revision_id": preset_revision.id,
                           "usage": copy.deepcopy(usage),
                           "provenance": copy.deepcopy(result.get("provenance") or {})}
    version_num = (db.scalar(select(func.count(TaxonomyCandidate.id)).where(
        TaxonomyCandidate.workspace_id == user.workspace_id)) or 0) + 1
    candidate = TaxonomyCandidate(workspace_id=user.workspace_id, version=f"candidate-{version_num}",
        base_release_id=base_release_id, base_hash=base_hash, proposal_heads=heads,
        content=content, content_hash=digest(content), created_by=user.id)
    db.add(candidate)
    activity(db, user, "taxonomy.curated", "taxonomy_candidate", candidate.id,
             version=candidate.version, preset_revision_id=preset_revision.id, usage=usage)
    db.commit()
    return candidate_view(candidate)


@app.get("/api/taxonomy")
def taxonomy(db: Session = Depends(get_db), user: User = Depends(get_user)):
    releases = db.scalars(select(TaxonomyRelease).where(TaxonomyRelease.workspace_id == user.workspace_id).order_by(TaxonomyRelease.created_at.desc())).all()
    proposals = db.scalars(select(TaxonomyProposal).where(TaxonomyProposal.workspace_id == user.workspace_id).order_by(TaxonomyProposal.created_at.desc())).all()
    candidates = db.scalars(select(TaxonomyCandidate).where(TaxonomyCandidate.workspace_id == user.workspace_id).order_by(TaxonomyCandidate.created_at.desc())).all()
    latest = releases[0].content if releases else {"labels": []}
    return {"releases": [{**record(r), "labels": (r.content or {}).get("labels", [])} for r in releases],
            "proposals": [proposal_view(db, p) for p in proposals],
            "candidates": [candidate_view(c) for c in candidates], "labels": latest.get("labels", [])}


@app.post("/api/taxonomy/proposals")
def create_proposal(body: TaxonomyProposalCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager", "reviewer"))):
    lock_taxonomy_workspace(db, user.workspace_id)
    release = db.get(TaxonomyRelease, body.base_release_id) if body.base_release_id else current_release(db, user.workspace_id)
    if release and release.workspace_id != user.workspace_id:
        raise HTTPException(404, "Base release not found")
    base_hash = release.content_hash if release else digest({"labels": []})
    if body.label_id and db.scalar(select(TaxonomyProposal.id).where(
            TaxonomyProposal.workspace_id == user.workspace_id, TaxonomyProposal.label_id == body.label_id)):
        raise HTTPException(409, "A draft already exists for this label; append a revision to that proposal")
    kind = {"new_label": "label", "edit_label": "edit", "retire_label": "retire"}.get(body.kind, body.kind)
    proposal = TaxonomyProposal(workspace_id=user.workspace_id, kind=kind,
                                label_id=body.label_id, base_release_id=release.id if release else None,
                                base_hash=base_hash, created_by=user.id)
    db.add(proposal)
    db.flush()
    content = {"name": body.name.strip(), "description": body.description.strip(), "evidence_refs": body.evidence_refs}
    rev = ProposalRevision(proposal_id=proposal.id, revision=1, name=content["name"],
                           description=content["description"], evidence_refs=content["evidence_refs"],
                           content_hash=digest(content), base_revision_hash=None, change_type="create", created_by=user.id)
    db.add(rev)
    db.flush()
    proposal.latest_revision_id = rev.id
    activity(db, user, "taxonomy.proposal_created", "taxonomy_proposal", proposal.id, kind=body.kind)
    db.commit()
    return proposal_view(db, proposal)


@app.patch("/api/taxonomy/proposals/{proposal_id}")
def edit_proposal(proposal_id: str, body: TaxonomyProposalCreate, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager", "reviewer"))):
    lock_taxonomy_workspace(db, user.workspace_id)
    proposal = db.get(TaxonomyProposal, proposal_id)
    if not proposal or proposal.workspace_id != user.workspace_id:
        raise HTTPException(404, "Proposal not found")
    previous = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
    release = db.get(TaxonomyRelease, body.base_release_id) if body.base_release_id else current_release(db, user.workspace_id)
    if release and release.workspace_id != user.workspace_id:
        raise HTTPException(404, "Base release not found")
    content = {"name": body.name.strip(), "description": body.description.strip(), "evidence_refs": body.evidence_refs}
    revision = ProposalRevision(proposal_id=proposal.id,
        revision=(previous.revision + 1 if previous else 1), name=content["name"],
        description=content["description"], evidence_refs=content["evidence_refs"],
        content_hash=digest(content), base_revision_hash=previous.content_hash if previous else None,
        change_type="edit", created_by=user.id)
    db.add(revision)
    db.flush()
    proposal.latest_revision_id = revision.id
    proposal.kind = {"new_label": "label", "edit_label": "edit", "retire_label": "retire"}.get(body.kind, body.kind)
    proposal.label_id = body.label_id
    proposal.base_release_id = release.id if release else None
    proposal.base_hash = release.content_hash if release else digest({"labels": []})
    activity(db, user, "taxonomy.proposal_edited", "taxonomy_proposal", proposal.id, revision=revision.revision)
    db.commit()
    return proposal_view(db, proposal)


@app.post("/api/taxonomy/proposals/{proposal_id}/feedback")
def proposal_feedback(proposal_id: str, body: ProposalFeedbackIn, db: Session = Depends(get_db), user: User = Depends(require_role("admin", "manager", "reviewer"))):
    lock_taxonomy_workspace(db, user.workspace_id)
    proposal = db.get(TaxonomyProposal, proposal_id)
    if not proposal or proposal.workspace_id != user.workspace_id:
        raise HTTPException(404, "Proposal not found")
    if not proposal.latest_revision_id:
        raise HTTPException(409, "Proposal has no revision")
    feedback = ProposalFeedback(proposal_id=proposal.id, proposal_revision_id=proposal.latest_revision_id,
                                text=body.text.strip(), created_by=user.id)
    db.add(feedback)
    # Feedback appends a proposal content revision, preserving previous revisions exactly.
    previous = db.get(ProposalRevision, proposal.latest_revision_id)
    content = {"name": previous.name, "description": previous.description,
               "evidence_refs": previous.evidence_refs, "feedback": body.text.strip()}
    revision = ProposalRevision(proposal_id=proposal.id, revision=previous.revision + 1,
                                name=previous.name, description=previous.description,
                                evidence_refs=previous.evidence_refs, content_hash=digest(content),
                                base_revision_hash=previous.content_hash, change_type="feedback", created_by=user.id)
    db.add(revision)
    db.flush()
    proposal.latest_revision_id = revision.id
    db.flush()
    feedback.proposal_revision_id = revision.id
    activity(db, user, "taxonomy.feedback_added", "taxonomy_proposal", proposal.id)
    db.commit()
    return proposal_view(db, proposal)


@app.post("/api/taxonomy/consolidate")
def consolidate_taxonomy(body: TaxonomyConsolidate | None = None, db: Session = Depends(get_db),
                         user: User = Depends(require_role("admin", "manager"))):
    body = body or TaxonomyConsolidate()
    if body.preset_revision_id:
        return _curate_taxonomy(db, user, body)
    if body.confirm_budget or body.expected_budget_usd is not None:
        raise HTTPException(422, "A preset revision is required for budget confirmation")
    lock_taxonomy_workspace(db, user.workspace_id)
    release = current_release(db, user.workspace_id)
    base_content = copy.deepcopy(release.content if release else {"labels": []})
    base_hash = release.content_hash if release else digest(base_content)
    proposals = db.scalars(select(TaxonomyProposal).where(TaxonomyProposal.workspace_id == user.workspace_id).order_by(TaxonomyProposal.created_at)).all()
    heads: dict[str, str] = {}
    entries = []
    for proposal in proposals:
        rev = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if rev:
            head = {"revision_hash": rev.content_hash, "base_hash": proposal.base_hash,
                    "base_release_id": proposal.base_release_id, "kind": proposal.kind,
                    "label_id": proposal.label_id}
            heads[proposal.id] = digest(head)
            entries.append({"proposal_id": proposal.id, "kind": proposal.kind, "label_id": proposal.label_id,
                            "name": rev.name, "description": rev.description,
                            "evidence_refs": rev.evidence_refs, "base_hash": proposal.base_hash,
                            "base_release_id": proposal.base_release_id})
    labels = copy.deepcopy(base_content.get("labels", []))
    mappings = []
    unresolved = []
    for entry in entries:
        kind = entry["kind"]
        proposal_id = entry["proposal_id"]
        label_id = entry["label_id"]
        target_id = label_id or proposal_id
        position = next((i for i, label in enumerate(labels) if str(label.get("id")) == str(target_id)), None)
        if kind in ("edit", "retire", "merge") and entry["base_hash"] != base_hash:
            unresolved.append({"proposal_id": proposal_id,
                               "reason": "Proposal base changed. Rebase and revise it before consolidation."})
            continue
        if kind in ("edit", "retire") and position is None:
            unresolved.append({"proposal_id": proposal_id, "reason": "Target label does not exist in base release."})
            continue
        if kind == "retire":
            labels[position] = {**labels[position], "status": "retired"}
            mappings.append({"proposal_id": proposal_id, "canonical_label_id": target_id,
                             "rationale": "Direct retirement proposal targeted this existing label."})
        elif kind == "edit":
            labels[position] = {**labels[position], "name": entry["name"],
                                "description": entry["description"], "status": "proposed_edit"}
            mappings.append({"proposal_id": proposal_id, "canonical_label_id": target_id,
                             "rationale": "Direct edit proposal targeted this existing label."})
        elif kind == "merge":
            if position is None:
                unresolved.append({"proposal_id": proposal_id,
                                   "reason": "Merge requires an existing target label ID."})
                continue
            mappings.append({"proposal_id": proposal_id, "canonical_label_id": target_id,
                             "rationale": "Draft proposal explicitly maps to the selected existing label."})
        else:
            labels.append({"id": target_id, "name": entry["name"], "description": entry["description"],
                           "status": "proposed", "evidence_refs": entry["evidence_refs"]})
            mappings.append({"proposal_id": proposal_id, "canonical_label_id": target_id,
                             "rationale": "Draft proposal retained as its own label pending human approval."})
    content = {**base_content, "labels": labels, "mappings": mappings,
               "unresolved": unresolved, "draft_proposals": entries}
    version_num = len(db.scalars(select(TaxonomyCandidate).where(TaxonomyCandidate.workspace_id == user.workspace_id)).all()) + 1
    candidate = TaxonomyCandidate(workspace_id=user.workspace_id, version=f"candidate-{version_num}",
        base_release_id=release.id if release else None, base_hash=base_hash, proposal_heads=heads,
        content=content, content_hash=digest(content), created_by=user.id)
    db.add(candidate)
    activity(db, user, "taxonomy.consolidated", "taxonomy_candidate", candidate.id, version=candidate.version)
    db.commit()
    return candidate_view(candidate)


@app.post("/api/taxonomy/candidates/{candidate_id}/approve")
def approve_candidate(candidate_id: str, body: CandidateApproval, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    lock_taxonomy_workspace(db, user.workspace_id)
    candidate = db.get(TaxonomyCandidate, candidate_id)
    if not candidate or candidate.workspace_id != user.workspace_id:
        raise HTTPException(404, "Candidate not found")
    decisions = db.scalars(select(CandidateDecision).where(CandidateDecision.candidate_id == candidate.id)).all()
    if any(item.action == "reject" for item in decisions):
        raise HTTPException(409, "A rejected candidate cannot be approved")
    if any(item.action == "approve" for item in decisions):
        raise HTTPException(409, "This candidate was already approved")
    latest = current_release(db, user.workspace_id)
    latest_hash = latest.content_hash if latest else digest({"labels": []})
    current_heads = {p.id: digest({"revision_hash": db.get(ProposalRevision, p.latest_revision_id).content_hash,
                                    "base_hash": p.base_hash, "base_release_id": p.base_release_id,
                                    "kind": p.kind, "label_id": p.label_id})
                     for p in db.scalars(select(TaxonomyProposal).where(TaxonomyProposal.workspace_id == user.workspace_id)).all()
                     if p.latest_revision_id and db.get(ProposalRevision, p.latest_revision_id)}
    if (candidate.content_hash != body.expected_hash or candidate.version != body.version or
            candidate.base_hash != latest_hash or candidate.proposal_heads != current_heads):
        raise HTTPException(409, "Candidate is stale: its hash, base release, or proposal revisions changed")
    content = candidate.content or {}
    unresolved = content.get("unresolved") or []
    if unresolved:
        raise HTTPException(409, "Candidate has unresolved proposal targets and cannot be published")
    # Only publish canonical labels supplied by an exact candidate. A draft proposal collection is not itself a label release.
    labels = copy.deepcopy((candidate.content or {}).get("labels", []))
    label_ids = [str(label.get("id") or "") for label in labels if isinstance(label, dict)]
    if len(label_ids) != len(labels) or any(not label_id for label_id in label_ids) or len(set(label_ids)) != len(label_ids):
        raise HTTPException(409, "Candidate contains missing or duplicate label IDs")
    for label in labels:
        label["status"] = "retired" if label.get("status") == "retired" else "active"
    release_content = {key: copy.deepcopy(value) for key, value in (candidate.content or {}).items()}
    version = f"{len(db.scalars(select(TaxonomyRelease).where(TaxonomyRelease.workspace_id == user.workspace_id)).all()) + 1}.0.0"
    release = TaxonomyRelease(workspace_id=user.workspace_id, version=version, content=release_content,
                              content_hash=digest(release_content), created_by=user.id)
    db.add(release)
    db.add(CandidateDecision(candidate_id=candidate.id, action="approve", expected_hash=body.expected_hash,
                             created_by=user.id))
    activity(db, user, "taxonomy.approved", "taxonomy_release", release.id, candidate_id=candidate.id,
             candidate_hash=candidate.content_hash)
    db.commit()
    return {**record(release), "labels": labels}


@app.post("/api/taxonomy/candidates/{candidate_id}/reject")
def reject_candidate(candidate_id: str, body: CandidateRejection, db: Session = Depends(get_db), user: User = Depends(require_role("admin"))):
    lock_taxonomy_workspace(db, user.workspace_id)
    candidate = db.get(TaxonomyCandidate, candidate_id)
    if not candidate or candidate.workspace_id != user.workspace_id:
        raise HTTPException(404, "Candidate not found")
    db.add(CandidateDecision(candidate_id=candidate.id, action="reject", expected_hash=candidate.content_hash,
                             reason=body.reason.strip(), created_by=user.id))
    activity(db, user, "taxonomy.rejected", "taxonomy_candidate", candidate.id, reason=body.reason.strip())
    db.commit()
    return {"candidate_id": candidate.id, "action": "reject"}


@app.post("/api/batches/{batch_id}/tasks/{task_id}/feedback")
@app.post("/api/runs/{batch_id}/tasks/{task_id}/feedback")
def create_task_feedback(batch_id: str, task_id: str, body: FeedbackCreate,
                         member_id: str | None = None,
                         db: Session = Depends(get_db), access=Depends(require_batch("reviewer"))):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    feedback = TaskFeedback(member_id=member.id, author_id=user.id, text=body.text.strip(),
                            step_id=body.step_id, episode_id=body.episode_id)
    db.add(feedback)
    activity(db, user, "task.feedback_added", "batch_member", member.id,
             step_id=body.step_id, episode_id=body.episode_id)
    db.commit()
    return record(feedback)


@app.get("/api/batches/{batch_id}/tasks/{task_id}/feedback")
@app.get("/api/runs/{batch_id}/tasks/{task_id}/feedback")
def list_task_feedback(batch_id: str, task_id: str, member_id: str | None = None,
                       db: Session = Depends(get_db), access=Depends(require_batch())):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    items = db.scalars(select(TaskFeedback).where(TaskFeedback.member_id == member.id).order_by(TaskFeedback.created_at)).all()
    return {"items": [record(f) for f in items], "total": len(items)}


@app.get("/api/batches/{batch_id}/tasks/{task_id}/export")
@app.get("/api/runs/{batch_id}/tasks/{task_id}/export")
def export_task(batch_id: str, task_id: str, format: str = Query("json", pattern="^(json|yaml)$"),
                member_id: str | None = None,
                db: Session = Depends(get_db), access=Depends(require_batch())):
    batch, user, _role = access
    member_query = select(BatchMember).where(BatchMember.batch_id == batch.id, BatchMember.task_id == task_id)
    if member_id:
        member_query = member_query.where(BatchMember.id == member_id)
    member = db.scalar(member_query.order_by(BatchMember.created_at.desc()).limit(1))
    if not member:
        raise HTTPException(404, "Task not found in batch")
    revision = db.get(TaskRevision, member.task_revision_id)
    result = task_view(db, revision.content, revision.id, task_id, revision.revision,
                       member, member_review(db, member))
    if format == "yaml":
        return PlainTextResponse(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), media_type="application/yaml")
    return result


@app.get("/api/artifacts/{task_id}/{relative_path:path}")
def get_artifact(task_id: str, relative_path: str, member_id: str | None = None,
                 revision_id: str | None = None,
                 db: Session = Depends(get_db), user: User = Depends(get_user)):
    norm = Path(relative_path).as_posix()
    if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts or "\x00" in relative_path:
        raise HTTPException(404, "Artifact not found")
    artifact_query = select(StoredArtifact).where(StoredArtifact.relative_path == norm,
                                                 StoredArtifact.workspace_id == user.workspace_id)
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
                allowed = _allowed(db, member.batch_id, user)
        # A member-scoped artifact never falls back to broader dataset authorization.
        if not allowed and candidate.member_id is None and candidate.task_revision_id:
            revision = db.get(TaskRevision, candidate.task_revision_id)
            definition = db.get(TaskDefinition, revision.task_definition_id) if revision else None
            if definition and definition.task_id == task_id:
                dataset = db.get(Dataset, definition.dataset_id)
                allowed = bool(dataset and dataset_role(db, dataset, user))
                if not allowed:
                    refs = db.scalars(select(BatchMember).where(BatchMember.task_revision_id == revision.id)).all()
                    allowed = any(_allowed(db, ref.batch_id, user) for ref in refs)
        if allowed:
            artifact, valid = candidate, True
            break
    if not valid:
        raise HTTPException(403, "You do not have access to this evidence")
    if artifact.object_key:
        try:
            body = create_artifact_store(settings).get(artifact.object_key)
        except FileNotFoundError:
            raise HTTPException(404, "Recorded artifact is missing")
    elif artifact.source_relative_path:
        path = _recorded_source_file(artifact.source_relative_path)
        if not path:
            raise HTTPException(404, "Recorded artifact is missing")
        body = path.read_bytes()
    else:
        raise HTTPException(404, "Recorded artifact is missing")
    if hashlib.sha256(body).hexdigest() != artifact.sha256:
        raise HTTPException(409, "Recorded artifact checksum mismatch")
    return Response(content=body, media_type=artifact.media_type,
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def _allowed(db: Session, batch_id: str, user: User) -> bool:
    try:
        get_batch(db, batch_id, user)
        return True
    except HTTPException:
        return False


def visible_batch_ids(db: Session, user: User) -> set[str]:
    """Return batches the user can read without granting workspace-wide visibility."""
    batches = select(Batch.id).where(Batch.workspace_id == user.workspace_id)
    if user.role in ("admin", "manager"):
        return set(db.scalars(batches).all())
    team_ids = db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user.id)).all()
    target_grant = BatchGrant.user_id == user.id
    if team_ids:
        target_grant = or_(target_grant, BatchGrant.team_id.in_(team_ids))
    statement = (select(distinct(BatchGrant.batch_id)).join(Batch, Batch.id == BatchGrant.batch_id)
                 .where(Batch.workspace_id == user.workspace_id, target_grant))
    return set(db.scalars(statement).all())


@app.exception_handler(IntegrityError)
def integrity_error_handler(_request: Request, _exc: IntegrityError):
    return Response(status_code=409, content=json.dumps({"detail": "A conflicting record already exists"}), media_type="application/json")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "Not found")
    dist = (PROJECT_ROOT / "platform" / "web" / "dist").resolve()
    if full_path:
        candidate = (dist / full_path).resolve()
        # Resolve symlinks before checking containment so a built asset cannot escape dist.
        if candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        # A missing asset request should remain a 404 rather than returning index.html
        # with the wrong content type and confusing the browser's module loader.
        if Path(full_path).suffix:
            raise HTTPException(404, "Not found")
    index = dist / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(404, "Frontend assets are not built; run the platform web build")
