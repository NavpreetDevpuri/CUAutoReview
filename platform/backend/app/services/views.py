"""Read models for tasks, jobs, dataset summaries and run progress returned by the API."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import config
from app.models import (
    Batch,
    BatchGrant,
    BatchMember,
    Dataset,
    Job,
    Preset,
    PresetRevision,
    ReviewResult,
    RunConfiguration,
    SyncWave,
    TaskDefinition,
    TaskRevision,
    TaxonomyRelease,
    Team,
    User,
)
from app.services.access import dataset_role, is_archived
from app.services.read_cache import (
    _chunks,
    job_attempts,
    member_artifacts,
    member_jobs,
    member_reviews,
    members_with_reviews,
    preload_attempts,
    preload_members,
    preload_rows,
    revision_artifacts,
    run_source_ids,
)
from app.services.records import record


def task_view(
    db: Session,
    content: dict[str, Any],
    revision_id: str,
    task_id: str,
    revision_number: int | None = None,
    member: BatchMember | None = None,
    review_result: ReviewResult | None = None,
):
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
    output["review_provenance"] = (
        copy.deepcopy(review_result.provenance)
        if review_result and isinstance(review_result.provenance, dict)
        else None
    )
    if member and content.get("review") is not None:
        output["source_review"] = copy.deepcopy(content["review"])
    output["review_kind"] = review_result.review_kind if review_result else (review or {}).get("review_kind")
    output["review_history"] = []
    if member:
        output["review_history"] = [record(item) for item in member_reviews(db, member.id)]
        jobs = member_jobs(db, member.id)
        output["jobs"] = [job_detail(db, job) for job in jobs]
        output["job_id"] = jobs[0].id if jobs else None
        artifact_rows = member_artifacts(db, member.id)
    else:
        output["jobs"] = []
        output["job_id"] = None
        artifact_rows = revision_artifacts(db, revision_id)
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
            suffix = (
                f"?member_id={quote(member.id, safe='')}"
                if member
                else f"?revision_id={quote(revision_id, safe='')}"
                if revision_id
                else ""
            )
            step["screenshot_url"] = (
                f"/api/artifacts/{quote(task_id, safe='')}/{quote(artifact.relative_path, safe='/')}{suffix}"
            )
            step["artifact_status"] = "recorded"
        elif rel:
            step["artifact_status"] = "missing"
    artifact_suffix = (
        f"?member_id={quote(member.id, safe='')}"
        if member
        else f"?revision_id={quote(revision_id, safe='')}"
        if revision_id
        else ""
    )
    output["artifacts"] = [
        record(a)
        | {"url": f"/api/artifacts/{quote(task_id, safe='')}/{quote(a.relative_path, safe='/')}{artifact_suffix}"}
        for a in artifact_rows
    ]
    output["raw_url"] = (
        f"/api/batches/{member.batch_id}/tasks/{quote(task_id, safe='')}/export"
        f"?format=json&member_id={quote(member.id, safe='')}"
        if member
        else None
    )
    return output


def member_review(db: Session, member: BatchMember) -> ReviewResult | None:
    reviews = member_reviews(db, member.id)
    return reviews[-1] if reviews else None


def job_detail(db: Session, job: Job) -> dict[str, Any]:
    item = record(job)
    preset = db.get(PresetRevision, job.preset_revision_id)
    item["backend"] = preset.backend if preset else None
    item["model"] = preset.model if preset else None
    item["budget_usd"] = preset.budget_usd if preset else None
    item["max_total_budget_usd"] = (
        float(preset.budget_usd) * job.max_attempts if preset and preset.budget_usd is not None else None
    )
    attempts = job_attempts(db, job.id)
    item["attempts"] = [record(attempt) for attempt in attempts]
    known_attempt_costs = [float(attempt.cost_usd) for attempt in attempts if attempt.cost_usd is not None]
    item["cumulative_cost_usd"] = sum(known_attempt_costs) if known_attempt_costs else None
    item["unknown_cost_attempts"] = sum(attempt.cost_usd is None for attempt in attempts)
    item["retry_eligible"] = job.status in ("failed", "completed") and job.attempt_count < job.max_attempts
    return item


def review_counts(review: dict | None) -> dict[str, Any]:
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
    return {
        "problem_count": len(episodes),
        "flagged_step_count": len(flagged_steps),
        "flagged_step_ids": sorted(flagged_steps),
        "recovery_step_count": recovery_step_count,
        "flagged_labels": [
            {"id": label_id, "name": label_name, "count": count}
            for (label_id, label_name), count in sorted(labels.items())
        ],
    }


def _image_ids(value: Any) -> list[str]:
    return sorted({str(item) for item in value if item is not None}) if isinstance(value, list) else []


def review_evidence(content: dict | None, review_result: ReviewResult | None) -> dict[str, Any]:
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
        source_ids = sorted(
            {
                str(step.get("step_id"))
                for step in (content or {}).get("steps", [])
                if isinstance(step, dict)
                and (step.get("screenshot") or step.get("screenshot_path") or step.get("screenshot_url"))
                and step.get("step_id") is not None
            }
        )
    supplied_ids = _image_ids(evidence.get("supplied_image_step_ids"))
    omitted_ids = _image_ids(evidence.get("omitted_image_step_ids"))
    cited_ids = _image_ids(evidence.get("cited_image_step_ids"))
    return {
        "evidence_mode": evidence.get("evidence_mode"),
        "source_image_step_ids": source_ids,
        "supplied_image_step_ids": supplied_ids,
        "omitted_image_step_ids": omitted_ids,
        "cited_image_step_ids": cited_ids,
        "image_selection": copy.deepcopy(evidence.get("image_selection")),
        "omitted_image_reason": evidence.get("omitted_image_reason"),
        "source_image_count": len(source_ids),
        "supplied_image_count": len(supplied_ids),
        "omitted_image_count": len(omitted_ids),
        "cited_image_count": len(cited_ids),
    }


def dataset_task_summary(db: Session, content: dict | None, members: list[BatchMember]) -> dict[str, Any]:
    model_groups: dict[tuple[str, str], dict[str, Any]] = {}
    current_results: list[tuple[ReviewResult, BatchMember]] = []
    historical_results: list[tuple[ReviewResult, BatchMember]] = []
    all_reviews = 0
    preload_members(db, members)
    for member in members:
        results = member_reviews(db, member.id)
        all_reviews += len(results)
        if results:
            current_results.append((results[-1], member))
            historical_results.extend((result, member) for result in results[:-1])
    current_counts = [review_counts(result.review) for result, _member in current_results]
    historical_counts = [review_counts(result.review) for result, _member in historical_results]

    def empty_model_group(key: tuple[str, str]) -> dict[str, Any]:
        return {
            "backend": key[0],
            "model": key[1],
            "current_review_count": 0,
            "historical_review_count": 0,
            "current_problem_count": 0,
            "historical_problem_count": 0,
            "current_recovery_step_count": 0,
            "historical_recovery_step_count": 0,
            "current_flagged_step_ids": set(),
            "historical_flagged_step_ids": set(),
            "current_flagged_labels": {},
            "historical_flagged_labels": {},
            "supplied_image_step_ids": set(),
            "omitted_image_step_ids": set(),
            "cited_image_step_ids": set(),
            "source_image_step_ids": set(),
            "known_cost_usd": 0.0,
            "unknown_cost_attempts": 0,
        }

    def grouped(result: ReviewResult, member: BatchMember, *, current: bool):
        key = (result.backend or "unknown", result.model or "unknown")
        group = model_groups.setdefault(key, empty_model_group(key))
        counts = review_counts(result.review)
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
        evidence = review_evidence(revision.content if revision else None, result)
        for field in (
            "source_image_step_ids",
            "supplied_image_step_ids",
            "omitted_image_step_ids",
            "cited_image_step_ids",
        ):
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
        for job in member_jobs(db, member.id):
            attempts = job_attempts(db, job.id)
            for attempt in attempts:
                if attempt.cost_usd is None:
                    total_unknown_attempts += 1
                else:
                    total_known_cost += float(attempt.cost_usd)
            key = (
                db.get(PresetRevision, job.preset_revision_id).backend
                if db.get(PresetRevision, job.preset_revision_id)
                else "unknown",
                db.get(PresetRevision, job.preset_revision_id).model
                if db.get(PresetRevision, job.preset_revision_id)
                else "unknown",
            )
            group = model_groups.setdefault(key, empty_model_group(key))
            group["known_cost_usd"] += sum(
                float(attempt.cost_usd) for attempt in attempts if attempt.cost_usd is not None
            )
            group["unknown_cost_attempts"] += sum(attempt.cost_usd is None for attempt in attempts)

    models = []
    for _key, group in sorted(model_groups.items()):
        entry = {key: value for key, value in group.items() if not key.endswith("_ids") and not key.endswith("_labels")}
        entry["current_flagged_step_count"] = len(group["current_flagged_step_ids"])
        entry["historical_flagged_step_count"] = len(group["historical_flagged_step_ids"])
        for prefix in ("current", "historical"):
            entry[f"{prefix}_flagged_labels"] = [
                {"id": label_id, "name": label_name, "count": count}
                for (label_id, label_name), count in sorted(group[f"{prefix}_flagged_labels"].items())
            ]
        for field in (
            "source_image_step_ids",
            "supplied_image_step_ids",
            "omitted_image_step_ids",
            "cited_image_step_ids",
        ):
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
    source_ids = sorted(
        {
            str(step.get("step_id"))
            for step in (content or {}).get("steps", [])
            if isinstance(step, dict)
            and (step.get("screenshot") or step.get("screenshot_path") or step.get("screenshot_url"))
            and step.get("step_id") is not None
        }
    )
    supplied_ids = sorted(
        {
            step_id
            for result, member in current_results
            for step_id in review_evidence(
                (
                    db.get(TaskRevision, member.task_revision_id).content
                    if db.get(TaskRevision, member.task_revision_id)
                    else None
                ),
                result,
            )["supplied_image_step_ids"]
        }
    )
    omitted_ids = sorted(
        {
            step_id
            for result, member in current_results
            for step_id in review_evidence(
                (
                    db.get(TaskRevision, member.task_revision_id).content
                    if db.get(TaskRevision, member.task_revision_id)
                    else None
                ),
                result,
            )["omitted_image_step_ids"]
        }
    )
    cited_ids = sorted(
        {
            step_id
            for result, member in current_results
            for step_id in review_evidence(
                (
                    db.get(TaskRevision, member.task_revision_id).content
                    if db.get(TaskRevision, member.task_revision_id)
                    else None
                ),
                result,
            )["cited_image_step_ids"]
        }
    )
    return {
        "run_count": len(members),
        "saved_review_count": len(current_results),
        "missing_review_count": max(0, len(members) - len(current_results)),
        "review_revision_count": all_reviews,
        "historical_review_count": len(historical_results),
        "problem_count": sum(item["problem_count"] for item in current_counts),
        "historical_problem_count": historical_problem_count,
        "flagged_step_count": len(current_flagged_steps),
        "historical_flagged_step_count": len(historical_flagged_steps),
        "recovery_step_count": recovery_count,
        "historical_recovery_step_count": historical_recovery_count,
        "flagged_labels": [
            {"id": label_id, "name": label_name, "count": count}
            for (label_id, label_name), count in sorted(labels.items())
        ],
        "source_image_step_ids": source_ids,
        "source_image_count": len(source_ids),
        "supplied_image_step_ids": supplied_ids,
        "supplied_image_count": len(supplied_ids),
        "omitted_image_step_ids": omitted_ids,
        "omitted_image_count": len(omitted_ids),
        "cited_image_step_ids": cited_ids,
        "cited_image_count": len(cited_ids),
        "known_cost_usd": total_known_cost,
        "unknown_cost_attempts": total_unknown_attempts,
        "models": models,
    }


def batch_progress(db: Session, batch: Batch) -> dict[str, Any]:
    members = db.scalars(select(BatchMember).where(BatchMember.batch_id == batch.id)).all()
    preload_rows(db, TaskRevision, {member.task_revision_id for member in members})
    reviewed_member_ids = members_with_reviews(db, [member.id for member in members])
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
            if member.id in reviewed_member_ids:
                saved_reviews += 1
            else:
                missing_reviews += 1
    jobs = db.scalars(select(Job).where(Job.batch_id == batch.id)).all()
    preload_attempts(db, jobs)
    preload_rows(db, PresetRevision, {job.preset_revision_id for job in jobs} | {batch.preset_revision_id})
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
        for attempt in job_attempts(db, job.id):
            if attempt.cost_usd is None:
                unknown_cost_attempts += 1
            else:
                known_cost_usd += float(attempt.cost_usd)
        if job.status == "failed":
            member = db.get(BatchMember, job.member_id)
            failed_jobs.append(
                {
                    "job_id": job.id,
                    "task_id": member.task_id if member else None,
                    "status": job.status,
                    "error": job.error,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "budget_usd": preset.budget_usd if preset else None,
                }
            )
    pinned = db.get(PresetRevision, batch.preset_revision_id)
    default_max_attempts = min(4, max(1, int(config.settings.max_job_attempts)))
    for member in reviewable_members:
        if member.id in job_member_ids:
            continue
        if pinned and pinned.budget_usd is not None:
            known_planned_allowance_usd += float(pinned.budget_usd) * default_max_attempts
        else:
            planned_allowance_complete = False
    return {
        "total": len(members),
        "completed": counts.get("completed", 0),
        "queued": counts.get("queued", 0),
        "running": counts.get("running", 0),
        "retrying": counts.get("retrying", 0),
        "failed": counts.get("failed", 0),
        "awaiting_review": counts.get("awaiting_review", 0),
        "status_counts": counts,
        "outcome_summary": outcomes,
        "saved_review_count": saved_reviews,
        "missing_review_count": missing_reviews,
        "job_status_counts": job_status_counts,
        "attempt_count": attempt_count,
        "retry_count": automatic_retry_count,
        "failed_jobs": failed_jobs,
        "planned_allowance_usd": known_planned_allowance_usd if planned_allowance_complete else None,
        "known_planned_allowance_usd": known_planned_allowance_usd,
        "known_cost_usd": known_cost_usd,
        "unknown_cost_attempts": unknown_cost_attempts,
        "planned_job_count": len(reviewable_members),
        "default_max_attempts": default_max_attempts,
    }


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
    result["taxonomy_release"] = (
        {**record(release), "labels": (release.content or {}).get("labels", [])} if release else None
    )
    result["batch"] = {
        key: value for key, value in result.items() if key not in ("progress", "waves", "grants", "batch")
    }
    result["batch"]["progress"] = result["progress"]
    return result


def run_detail(db: Session, batch: Batch, user: User) -> dict[str, Any]:
    output = batch_detail(db, batch)
    output["archived"] = is_archived(db, "run", batch.id)
    source_ids = run_source_ids(db, batch)
    if not source_ids:
        source_ids = [batch.dataset_id]
    output["dataset_ids"] = source_ids
    source_datasets = []
    for source_id in source_ids:
        dataset = db.get(Dataset, source_id)
        if not dataset:
            continue
        included_tasks = (
            db.scalar(
                select(func.count(func.distinct(BatchMember.task_definition_id)))
                .select_from(BatchMember)
                .join(TaskDefinition, TaskDefinition.id == BatchMember.task_definition_id)
                .where(BatchMember.batch_id == batch.id, TaskDefinition.dataset_id == dataset.id)
            )
            or 0
        )
        current_definitions = db.scalars(select(TaskDefinition.id).where(TaskDefinition.dataset_id == dataset.id)).all()
        dataset_access = bool(dataset_role(db, dataset, user)) and not is_archived(db, "dataset", dataset.id)
        total_tasks = sum(not is_archived(db, "task", definition_id) for definition_id in current_definitions)
        source_datasets.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "archived": is_archived(db, "dataset", dataset.id),
                "task_count": int(included_tasks),
                "partial_access": not dataset_access,
                **({"total_task_count": total_tasks} if dataset_access else {}),
            }
        )
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
        execution_snapshot = (
            {
                "backend": pinned.backend,
                "model": pinned.model,
                "reasoning": pinned.reasoning,
                "budget_usd": pinned.budget_usd,
                "configuration": pinned.configuration,
            }
            if pinned
            else {}
        )
        rerun_of, config_revision = None, 1
    output["configuration"] = {
        "workflow_revision_id": workflow_id,
        "workflow_snapshot": workflow_snapshot,
        "execution_snapshot": execution_snapshot,
        "revision": config_revision,
        "rerun_of_run_id": rerun_of,
    }
    return output


def review_problem_count(review: dict | None) -> int:
    episodes = review.get("episodes") if isinstance(review, dict) else None
    return len(episodes) if isinstance(episodes, list) else 0


def batch_members_by_batch(db: Session, batches: list[Batch]) -> dict[str, list[BatchMember]]:
    """Load members of several runs in one pass, grouped by run."""
    grouped: dict[str, list[BatchMember]] = {batch.id: [] for batch in batches}
    for chunk in _chunks(sorted(grouped)):
        for member in db.scalars(select(BatchMember).where(BatchMember.batch_id.in_(chunk))).all():
            grouped[member.batch_id].append(member)
    return grouped
