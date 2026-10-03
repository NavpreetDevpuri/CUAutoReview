"""Request-scoped read cache that bulk-loads rows so list endpoints avoid per-row queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import distinct, event, select
from sqlalchemy.orm import Session

from app.models import (
    Batch,
    BatchGrant,
    BatchMember,
    DatasetShare,
    Job,
    JobAttempt,
    ObjectArchive,
    PresetRevision,
    ReviewResult,
    RunSource,
    StoredArtifact,
    TaskRevision,
    TeamMember,
)

# Request-scoped read cache. List and summary endpoints touch the same small
# tables for every row; loading them once per session keeps query counts flat
# as tasks and runs grow. Any flush, commit or rollback drops the cache, so a
# write path never reads rows that are older than its own changes.
READ_CACHE_CHUNK = 500


@event.listens_for(Session, "after_flush")
@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _drop_read_cache(session: Session, *_args) -> None:
    session.info.pop("read_cache", None)


def _read_cache(db: Session) -> dict[Any, Any]:
    return db.info.setdefault("read_cache", {})


def _chunks(values: list[str]):
    for start in range(0, len(values), READ_CACHE_CHUNK):
        yield values[start : start + READ_CACHE_CHUNK]


def preload_rows(db: Session, model: Any, ids) -> None:
    """Load rows by primary key in bulk so later db.get() calls resolve from the identity map.

    The identity map holds weak references, so the cache keeps the loaded rows alive.
    """
    loaded = _read_cache(db).setdefault(("rows", model), {})
    wanted = sorted({item for item in ids if item is not None and item not in loaded})
    for chunk in _chunks(wanted):
        for row in db.scalars(select(model).where(model.id.in_(chunk))).all():
            loaded[row.id] = row


def archived_objects(db: Session, object_type: str) -> dict[str, datetime]:
    """Map archived object IDs of one type to their archive time."""
    cache = _read_cache(db)
    key = ("archived", object_type)
    if key not in cache:
        cache[key] = dict(
            db.execute(
                select(ObjectArchive.object_id, ObjectArchive.archived_at).where(
                    ObjectArchive.object_type == object_type, ObjectArchive.archived_at.is_not(None)
                )
            ).all()
        )
    return cache[key]


def user_team_ids(db: Session, user_id: str) -> set[str]:
    cache = _read_cache(db).setdefault("team_ids", {})
    if user_id not in cache:
        cache[user_id] = set(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == user_id)).all())
    return cache[user_id]


def dataset_shares(db: Session, workspace_id: str, dataset_id: str) -> list[DatasetShare]:
    cache = _read_cache(db)
    key = ("dataset_shares", workspace_id)
    if key not in cache:
        by_dataset: dict[str, list[DatasetShare]] = {}
        for share in db.scalars(select(DatasetShare).where(DatasetShare.workspace_id == workspace_id)).all():
            by_dataset.setdefault(share.dataset_id, []).append(share)
        cache[key] = by_dataset
    return cache[key].get(dataset_id, [])


def run_source_ids(db: Session, batch: Batch) -> list[str]:
    """Return a run's source dataset IDs in position order; empty for legacy single-source batches."""
    cache = _read_cache(db)
    key = ("run_sources", batch.workspace_id)
    if key not in cache:
        by_batch: dict[str, list[str]] = {}
        for batch_id, dataset_id in db.execute(
            select(RunSource.batch_id, RunSource.dataset_id)
            .join(Batch, Batch.id == RunSource.batch_id)
            .where(Batch.workspace_id == batch.workspace_id)
            .order_by(RunSource.batch_id, RunSource.position)
        ).all():
            by_batch.setdefault(batch_id, []).append(dataset_id)
        cache[key] = by_batch
    return list(cache[key].get(batch.id, []))


def batch_grants(db: Session, batch: Batch) -> list[BatchGrant]:
    cache = _read_cache(db)
    key = ("batch_grants", batch.workspace_id)
    if key not in cache:
        by_batch: dict[str, list[BatchGrant]] = {}
        for grant in db.scalars(
            select(BatchGrant)
            .join(Batch, Batch.id == BatchGrant.batch_id)
            .where(Batch.workspace_id == batch.workspace_id)
        ).all():
            by_batch.setdefault(grant.batch_id, []).append(grant)
        cache[key] = by_batch
    return cache[key].get(batch.id, [])


def preload_members(db: Session, members: list[BatchMember]) -> None:
    """Bulk-load the reviews, jobs, attempts and revisions that per-member helpers read."""
    cache = _read_cache(db)
    member_ids = {member.id for member in members}
    reviews = cache.setdefault("member_reviews", {})
    for chunk in _chunks(sorted(member_ids - reviews.keys())):
        for member_id in chunk:
            reviews[member_id] = []
        for result in db.scalars(
            select(ReviewResult)
            .where(ReviewResult.member_id.in_(chunk))
            .order_by(ReviewResult.member_id, ReviewResult.revision)
        ).all():
            reviews[result.member_id].append(result)
    jobs = cache.setdefault("member_jobs", {})
    for chunk in _chunks(sorted(member_ids - jobs.keys())):
        for member_id in chunk:
            jobs[member_id] = []
        for job in db.scalars(select(Job).where(Job.member_id.in_(chunk)).order_by(Job.created_at)).all():
            jobs[job.member_id].append(job)
    job_rows = [job for member_id in member_ids for job in jobs[member_id]]
    preload_attempts(db, job_rows)
    preload_rows(db, PresetRevision, {job.preset_revision_id for job in job_rows})
    preload_rows(db, TaskRevision, {member.task_revision_id for member in members})


def preload_attempts(db: Session, jobs: list[Job]) -> None:
    attempts = _read_cache(db).setdefault("job_attempts", {})
    for chunk in _chunks(sorted({job.id for job in jobs} - attempts.keys())):
        for job_id in chunk:
            attempts[job_id] = []
        for attempt in db.scalars(
            select(JobAttempt)
            .where(JobAttempt.job_id.in_(chunk))
            .order_by(JobAttempt.job_id, JobAttempt.attempt_number)
        ).all():
            attempts[attempt.job_id].append(attempt)


def member_reviews(db: Session, member_id: str) -> list[ReviewResult]:
    """All saved review revisions for a member, oldest first."""
    reviews = _read_cache(db).setdefault("member_reviews", {})
    if member_id not in reviews:
        reviews[member_id] = db.scalars(
            select(ReviewResult).where(ReviewResult.member_id == member_id).order_by(ReviewResult.revision)
        ).all()
    return reviews[member_id]


def members_with_reviews(db: Session, member_ids: list[str]) -> set[str]:
    """Return members that have at least one saved review, without loading review payloads."""
    reviews = _read_cache(db).get("member_reviews", {})
    found = {member_id for member_id in member_ids if reviews.get(member_id)}
    for chunk in _chunks(sorted({member_id for member_id in member_ids if member_id not in reviews})):
        found.update(
            db.scalars(select(distinct(ReviewResult.member_id)).where(ReviewResult.member_id.in_(chunk))).all()
        )
    return found


def member_jobs(db: Session, member_id: str) -> list[Job]:
    jobs = _read_cache(db).setdefault("member_jobs", {})
    if member_id not in jobs:
        jobs[member_id] = db.scalars(select(Job).where(Job.member_id == member_id).order_by(Job.created_at)).all()
    return jobs[member_id]


def job_attempts(db: Session, job_id: str) -> list[JobAttempt]:
    attempts = _read_cache(db).setdefault("job_attempts", {})
    if job_id not in attempts:
        attempts[job_id] = db.scalars(
            select(JobAttempt).where(JobAttempt.job_id == job_id).order_by(JobAttempt.attempt_number)
        ).all()
    return attempts[job_id]


def preload_artifacts(db: Session, *, revision_ids=(), member_ids=()) -> None:
    """Bulk-load stored artifact rows keyed by task revision and by member."""
    cache = _read_cache(db)
    by_revision = cache.setdefault("revision_artifacts", {})
    for chunk in _chunks(sorted({item for item in revision_ids if item} - by_revision.keys())):
        for revision_id in chunk:
            by_revision[revision_id] = []
        for artifact in db.scalars(select(StoredArtifact).where(StoredArtifact.task_revision_id.in_(chunk))).all():
            by_revision[artifact.task_revision_id].append(artifact)
    by_member = cache.setdefault("member_artifacts", {})
    for chunk in _chunks(sorted({item for item in member_ids if item} - by_member.keys())):
        for member_id in chunk:
            by_member[member_id] = []
        for artifact in db.scalars(select(StoredArtifact).where(StoredArtifact.member_id.in_(chunk))).all():
            by_member[artifact.member_id].append(artifact)


def revision_artifacts(db: Session, revision_id: str) -> list[StoredArtifact]:
    by_revision = _read_cache(db).setdefault("revision_artifacts", {})
    if revision_id not in by_revision:
        by_revision[revision_id] = db.scalars(
            select(StoredArtifact).where(StoredArtifact.task_revision_id == revision_id)
        ).all()
    return by_revision[revision_id]


def member_artifacts(db: Session, member_id: str) -> list[StoredArtifact]:
    by_member = _read_cache(db).setdefault("member_artifacts", {})
    if member_id not in by_member:
        by_member[member_id] = db.scalars(select(StoredArtifact).where(StoredArtifact.member_id == member_id)).all()
    return by_member[member_id]
