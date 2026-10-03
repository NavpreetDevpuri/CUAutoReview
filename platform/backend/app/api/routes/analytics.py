"""Selection catalog, filtered analytics and review comparison."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_user
from app.core.database import get_db
from app.models import Batch, BatchMember, Dataset, ReviewResult, TaskDefinition, TaskRevision, User
from app.schemas import AnalyticsCompare, AnalyticsQuery
from app.services.access import dataset_role, get_batch, is_archived, visible_batches
from app.services.evidence import recorded_source_file
from app.services.read_cache import (
    job_attempts,
    member_jobs,
    preload_artifacts,
    preload_members,
    preload_rows,
    revision_artifacts,
    run_source_ids,
)
from app.services.records import canonical, iso
from app.services.tasks import current_revision
from app.services.views import batch_members_by_batch, dataset_task_summary, member_review, review_problem_count

router = APIRouter()


@router.get("/api/catalog")
def selection_catalog(include_archived: bool = False, db: Session = Depends(get_db), user: User = Depends(get_user)):
    datasets = db.scalars(select(Dataset).where(Dataset.workspace_id == user.workspace_id).order_by(Dataset.name)).all()
    datasets = [
        dataset
        for dataset in datasets
        if dataset_role(db, dataset, user) and (include_archived or not is_archived(db, "dataset", dataset.id))
    ]
    accessible_datasets = {dataset.id: dataset for dataset in datasets}
    batches = visible_batches(db, user, include_archived)
    run_rows = []
    run_members = batch_members_by_batch(db, batches)
    preload_members(db, [member for members in run_members.values() for member in members])
    members_by_run_task: dict[tuple[str, str], list[BatchMember]] = {}
    for batch_id, members in run_members.items():
        for member in members:
            members_by_run_task.setdefault((batch_id, member.task_definition_id), []).append(member)
    for batch in batches:
        members = run_members[batch.id]
        problems = sum(
            review_problem_count(member_review(db, member).review if member_review(db, member) else None)
            for member in members
        )
        sources = run_source_ids(db, batch) or [batch.dataset_id]
        visible_sources = [source_id for source_id in sources if source_id in accessible_datasets]
        run_rows.append(
            {
                "id": batch.id,
                "name": batch.name,
                "dataset_ids": visible_sources,
                "task_count": len(members),
                "status": batch.status,
                "problem_count": problems,
                "archived": is_archived(db, "run", batch.id),
                "partial_access": len(visible_sources) < len(sources),
            }
        )
    task_rows, dataset_rows = [], []
    for dataset in datasets:
        definitions = db.scalars(
            select(TaskDefinition).where(TaskDefinition.dataset_id == dataset.id).order_by(TaskDefinition.task_id)
        ).all()
        if not include_archived:
            definitions = [definition for definition in definitions if not is_archived(db, "task", definition.id)]
        preload_rows(db, TaskRevision, {definition.current_revision_id for definition in definitions})
        problem_total = 0
        run_ids_for_dataset = {
            batch.id for batch in batches if dataset.id in (run_source_ids(db, batch) or [batch.dataset_id])
        }
        for definition in definitions:
            revision = current_revision(db, definition)
            if not revision:
                continue
            memberships = [
                member
                for run_id in run_ids_for_dataset
                for member in members_by_run_task.get((run_id, definition.id), [])
            ]
            problems = sum(
                review_problem_count(latest.review if (latest := member_review(db, member)) else None)
                for member in memberships
            )
            problem_total += problems
            content = revision.content or {}
            task_rows.append(
                {
                    "id": definition.id,
                    "task_definition_id": definition.id,
                    "dataset_id": dataset.id,
                    "task_id": definition.task_id,
                    "title": content.get("title") or definition.task_id,
                    "outcome": content.get("outcome") or "unknown",
                    "step_count": len(content.get("steps") or []),
                    "run_count": len({m.batch_id for m in memberships}),
                    "problem_count": problems,
                    "archived": is_archived(db, "task", definition.id),
                    "summary": dataset_task_summary(db, content, memberships),
                }
            )
        dataset_rows.append(
            {
                "id": dataset.id,
                "name": dataset.name,
                "task_count": len(definitions),
                "run_count": len(run_ids_for_dataset),
                "problem_count": problem_total,
                "archived": is_archived(db, "dataset", dataset.id),
            }
        )
    return {"datasets": dataset_rows, "runs": run_rows, "tasks": task_rows}


@router.post("/api/analytics/query")
def analytics_query(body: AnalyticsQuery, db: Session = Depends(get_db), user: User = Depends(get_user)):
    catalog_datasets = db.scalars(select(Dataset).where(Dataset.workspace_id == user.workspace_id)).all()
    accessible_datasets = {
        dataset.id: dataset
        for dataset in catalog_datasets
        if dataset_role(db, dataset, user) and (body.include_archived or not is_archived(db, "dataset", dataset.id))
    }
    if body.dataset_ids:
        if len(set(body.dataset_ids)) != len(body.dataset_ids) or any(
            item not in accessible_datasets for item in body.dataset_ids
        ):
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
        authorized_member_ids = set(
            db.scalars(
                select(BatchMember.task_definition_id).where(
                    BatchMember.batch_id.in_(selected_run_ids) if selected_run_ids else False
                )
            ).all()
        )
        authorized_members = db.scalars(
            select(TaskDefinition).where(
                TaskDefinition.id.in_(authorized_member_ids) if authorized_member_ids else False
            )
        ).all()
        accessible_definitions = db.scalars(
            select(TaskDefinition).where(
                TaskDefinition.dataset_id.in_(accessible_datasets) if accessible_datasets else False
            )
        ).all()
        definitions_by_id = {definition.id: definition for definition in accessible_definitions}
        definitions_by_id.update({definition.id: definition for definition in authorized_members})
        definitions = list(definitions_by_id.values())
        selected_dataset_ids.update(definition.dataset_id for definition in authorized_members)
    else:
        definitions = db.scalars(
            select(TaskDefinition).where(TaskDefinition.dataset_id.in_(selected_dataset_ids))
            if selected_dataset_ids
            else select(TaskDefinition).where(False)
        ).all()
    definitions = [
        definition for definition in definitions if body.include_archived or not is_archived(db, "task", definition.id)
    ]
    if body.task_definition_ids:
        by_id = {definition.id: definition for definition in definitions}
        if len(set(body.task_definition_ids)) != len(body.task_definition_ids) or any(
            item not in by_id for item in body.task_definition_ids
        ):
            raise HTTPException(404, "Selected task definition not found")
        selected_definition_ids = set(body.task_definition_ids)
    else:
        selected_definition_ids = {definition.id for definition in definitions}

    member_rows: list[BatchMember] = []
    selected_members = batch_members_by_batch(db, selected_batches)
    for batch in selected_batches:
        sources = set(run_source_ids(db, batch)) or {batch.dataset_id}
        for member in selected_members[batch.id]:
            if member.task_definition_id not in selected_definition_ids:
                continue
            definition = db.get(TaskDefinition, member.task_definition_id)
            if (
                definition
                and definition.dataset_id in selected_dataset_ids
                and sources.intersection(selected_dataset_ids)
            ):
                member_rows.append(member)
    preload_members(db, member_rows)
    preload_rows(
        db,
        TaskRevision,
        {definition.current_revision_id for definition in definitions if definition.id in selected_definition_ids},
    )
    preload_artifacts(
        db,
        revision_ids={member.task_revision_id for member in member_rows}
        | {definition.current_revision_id for definition in definitions if definition.id in selected_definition_ids},
    )

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
            recovery_step_count += (
                len(recovery.get("step_ids", [])) if isinstance(recovery.get("step_ids"), list) else 0
            )
            label_id = str(episode.get("label_id") or "unlabeled")
            label_name = str(episode.get("label_name") or label_id)
            key = (label_id, label_name)
            label_counts[key] = label_counts.get(key, 0) + 1
            labels_for_row.append({"id": label_id, "name": label_name})
        recovery_count += recovery_step_count
        revision_rows = [
            artifact for artifact in revision_artifacts(db, revision.id) if artifact.member_id in (member.id, None)
        ]
        recorded = {artifact.relative_path for artifact in revision_rows if artifact.workspace_id == user.workspace_id}
        steps = [step for step in content.get("steps", []) if isinstance(step, dict)]
        absent_frames = sum(1 for step in steps if not (step.get("screenshot") or step.get("screenshot_path")))
        screenshot_paths = [
            step.get("screenshot") or step.get("screenshot_path")
            for step in steps
            if step.get("screenshot") or step.get("screenshot_path")
        ]
        missing_records = sum(1 for path in screenshot_paths if path not in recorded)
        artifact_rows = [
            artifact for artifact in revision_rows if artifact.relative_path in (screenshot_paths or ["__none__"])
        ]
        broken_sources = sum(
            1
            for artifact in artifact_rows
            if artifact.source_relative_path and not recorded_source_file(artifact.source_relative_path)
        )
        absent_frame_steps += absent_frames
        missing_artifact_records += missing_records
        broken_source_files += broken_sources
        jobs = member_jobs(db, member.id)
        member_known_cost, member_unknown_jobs, member_unknown_attempts = 0.0, 0, 0
        for job in jobs:
            attempts = job_attempts(db, job.id)
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
        rows.append(
            {
                "run_id": batch.id,
                "run_name": batch.name,
                "dataset_id": definition.dataset_id,
                "task_definition_id": definition.id,
                "task_id": definition.task_id,
                "task_title": content.get("title") or definition.task_id,
                "task_revision_id": revision.id,
                "task_revision": revision.revision,
                "member_id": member.id,
                "review_result_id": review_result.id if review_result else None,
                "review_revision": review_result.revision if review_result else None,
                "status": member.status,
                "outcome": outcome,
                "review_kind": member.review_kind,
                "problem_count": len(episodes),
                "labels": labels_for_row,
                "recovery_step_count": recovery_step_count,
                "absent_frame_steps": absent_frames,
                "missing_artifact_records": missing_records,
                "broken_source_files": broken_sources,
                "known_cost_usd": member_known_cost,
                "unknown_cost_jobs": member_unknown_jobs,
                "unknown_cost_attempts": member_unknown_attempts,
            }
        )

    # Preserve selected tasks with no run membership as explicit not-run rows.
    if not body.run_ids:
        for definition in definitions:
            if definition.id not in selected_definition_ids or definition.id in seen_definitions:
                continue
            revision = current_revision(db, definition)
            if not revision:
                continue
            content = revision.content or {}
            source_artifacts = [
                artifact for artifact in revision_artifacts(db, revision.id) if artifact.member_id is None
            ]
            artifacts = {artifact.relative_path for artifact in source_artifacts}
            steps = [step for step in content.get("steps", []) if isinstance(step, dict)]
            absent_frames = sum(1 for step in steps if not (step.get("screenshot") or step.get("screenshot_path")))
            screenshot_paths = [
                step.get("screenshot") or step.get("screenshot_path")
                for step in steps
                if step.get("screenshot") or step.get("screenshot_path")
            ]
            missing_records = sum(1 for path in screenshot_paths if path not in artifacts)
            artifact_rows = [
                artifact
                for artifact in source_artifacts
                if artifact.relative_path in (screenshot_paths or ["__none__"])
            ]
            broken_sources = sum(
                1
                for artifact in artifact_rows
                if artifact.source_relative_path and not recorded_source_file(artifact.source_relative_path)
            )
            absent_frame_steps += absent_frames
            missing_artifact_records += missing_records
            broken_source_files += broken_sources
            outcome = str(content.get("outcome") or "unknown")
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            status_counts["not_run"] = status_counts.get("not_run", 0) + 1
            rows.append(
                {
                    "run_id": None,
                    "run_name": None,
                    "dataset_id": definition.dataset_id,
                    "task_definition_id": definition.id,
                    "task_id": definition.task_id,
                    "task_title": content.get("title") or definition.task_id,
                    "task_revision_id": revision.id,
                    "task_revision": revision.revision,
                    "member_id": None,
                    "review_result_id": None,
                    "review_revision": None,
                    "status": "not_run",
                    "outcome": outcome,
                    "review_kind": None,
                    "problem_count": 0,
                    "labels": [],
                    "recovery_step_count": 0,
                    "absent_frame_steps": absent_frames,
                    "missing_artifact_records": missing_records,
                    "broken_source_files": broken_sources,
                    "known_cost_usd": 0.0,
                    "unknown_cost_jobs": 0,
                    "unknown_cost_attempts": 0,
                }
            )
    return {
        "filters": {
            "dataset_ids": sorted(selected_dataset_ids),
            "run_ids": sorted(selected_run_ids),
            "task_definition_ids": sorted(selected_definition_ids),
        },
        "counts": {
            "task_definitions": len({row["task_definition_id"] for row in rows}),
            "selected_task_definitions": len(selected_definition_ids),
            "rows": len(rows),
            "run_members": len(member_rows),
            "problem_episodes": problem_count,
            "recovery_steps": recovery_count,
            "absent_frame_steps": absent_frame_steps,
            "missing_artifact_records": missing_artifact_records,
            "broken_source_files": broken_source_files,
            "missing_evidence": absent_frame_steps + missing_artifact_records + broken_source_files,
            "outcomes": outcome_counts,
            "statuses": status_counts,
            "cost_usd": None if unknown_cost_jobs else known_cost,
            "known_cost_usd": known_cost,
            "unknown_cost_jobs": unknown_cost_jobs,
            "unknown_cost_attempts": unknown_cost_attempts,
        },
        "labels": [
            {"id": label_id, "name": label_name, "count": count}
            for (label_id, label_name), count in sorted(label_counts.items())
        ],
        "rows": rows,
    }


@router.post("/api/analytics/compare")
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
    return {
        "aligned": {
            "task_definition_id": first_member.task_definition_id,
            "task_id": task_definition.task_id if task_definition else first_member.task_id,
            "task_revision_id": first_member.task_revision_id,
            "task_revision": revision.revision if revision else None,
        },
        "results": [
            {
                "id": result.id,
                "member_id": member.id,
                "run_id": member.batch_id,
                "task_id": member.task_id,
                "revision": result.revision,
                "review_kind": result.review_kind,
                "backend": result.backend,
                "model": result.model,
                "review": result.review,
                "created_at": iso(result.created_at),
            }
            for result, member in results
        ],
        "differences": differences,
        "verdict": None,
    }
