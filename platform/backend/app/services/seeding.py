"""First-workspace seeding from the retained POC run, without model calls."""

from __future__ import annotations

import copy
import json

from sqlalchemy.orm import Session

from app.core import config
from app.models import (
    Batch,
    Dataset,
    Preset,
    PresetRevision,
    ProposalRevision,
    SyncWave,
    TaskDefinition,
    TaskRevision,
    TaxonomyProposal,
    User,
)
from app.services.audit import activity
from app.services.records import digest
from app.services.runs import add_member
from app.services.tasks import current_revision, task_definitions
from app.services.taxonomy_lock import lock_taxonomy_workspace


def seed_first_workspace(db: Session, user: User):
    """Import the retained POC's latest completed fixture without invoking a model."""
    if not config.settings.seed_poc:
        return
    run_path = config.PROJECT_ROOT / "poc" / "runs" / "latest" / "run.json"
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
    dataset = Dataset(
        workspace_id=user.workspace_id,
        name="Saved POC examples",
        description="Five retained trajectory reviews. These are replayed source evidence, not new inference.",
        source_adapter="cuautoreview",
        created_by=user.id,
    )
    db.add(dataset)
    preset = Preset(workspace_id=user.workspace_id, name="Saved replay (retained evidence)", created_by=user.id)
    db.add(preset)
    db.flush()
    replay_config = {"replay": True, "description": "Replays retained POC evidence; makes no model calls."}
    revision = PresetRevision(
        preset_id=preset.id,
        revision=1,
        backend="saved_replay",
        model="retained-poc",
        reasoning="none",
        budget_usd=0.0,
        configuration=replay_config,
        config_hash=digest(replay_config),
        created_by=user.id,
    )
    db.add(revision)
    for task in tasks:
        task_id = str(task.get("task_id", ""))
        if not task_id:
            continue
        content = copy.deepcopy(task)
        content["original_run_id"] = run.get("run_id")
        content["provenance"] = {
            "run_id": run.get("run_id"),
            "run_status": run.get("status"),
            "saved_replay": True,
            "source": task.get("source", {}),
        }
        content["original_model"] = run.get("model")
        content["original_dedup_model"] = run.get("dedup_model")
        content["original_reasoning_effort"] = run.get("reasoning_effort")
        content["original_prompt_sha256"] = copy.deepcopy(run.get("prompt_sha256"))
        defn = TaskDefinition(dataset_id=dataset.id, task_id=task_id)
        db.add(defn)
        db.flush()
        task_rev = TaskRevision(
            task_definition_id=defn.id, revision=1, source_revision=digest(content), content=content
        )
        db.add(task_rev)
        db.flush()
        defn.current_revision_id = task_rev.id
    # Wave and batch reference each other; insert the batch to materialize its generated ID.
    batch = Batch(
        workspace_id=user.workspace_id,
        dataset_id=dataset.id,
        name="Retained POC replay",
        description="Fixture evidence from the most recent completed POC run.",
        mode="fixed",
        preset_revision_id=revision.id,
        status="completed",
        created_by=user.id,
    )
    db.add(batch)
    db.flush()
    wave = SyncWave(batch_id=batch.id, number=1, sync_key="seed-initial", task_count=len(tasks), created_by=user.id)
    db.add(wave)
    db.flush()
    definitions = {item.task_id: item for item in task_definitions(db, dataset.id)}
    for definition in definitions.values():
        task_rev = current_revision(db, definition)
        if task_rev:
            add_member(
                db,
                batch,
                definition,
                task_rev,
                wave.id,
                user,
                status="completed" if task_rev.content.get("review") else "awaiting_review",
            )
    # Keep the taxonomy as an editable proposal draft. No consolidation or inference runs here.
    proposals_path = config.PROJECT_ROOT / "poc" / "runs" / str(run.get("run_id")) / "proposals.json"
    try:
        pool = json.loads(proposals_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pool = {"proposals": []}
    seed_base_hash = digest({"labels": []})
    for item in pool.get("proposals", []):
        proposal = TaxonomyProposal(
            workspace_id=user.workspace_id,
            kind="label",
            label_id=item.get("id") or item.get("target_label_id") or None,
            base_hash=seed_base_hash,
            created_by=user.id,
        )
        db.add(proposal)
        db.flush()
        body = {
            "name": item.get("name") or "Untitled label",
            "description": item.get("description") or "",
            "evidence_refs": item.get("evidence_refs") or [],
        }
        pr = ProposalRevision(
            proposal_id=proposal.id,
            revision=1,
            name=body["name"],
            description=body["description"],
            evidence_refs=body["evidence_refs"],
            content_hash=digest(body),
            base_revision_hash=None,
            change_type="create",
            created_by=user.id,
        )
        db.add(pr)
        db.flush()
        proposal.latest_revision_id = pr.id
    activity(
        db,
        user,
        "workspace.seeded",
        "workspace",
        user.workspace_id,
        task_count=len(tasks),
        run_id=run.get("run_id"),
        saved_replay=True,
        inference_calls=0,
    )
