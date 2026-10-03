"""SQLAlchemy records for the local review workspace."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Normalize timestamps read from databases that drop timezone metadata (e.g. SQLite)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def uid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="viewer", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_team_workspace_name"),)


class TeamMember(Base):
    __tablename__ = "team_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member"),)


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    source_adapter: Mapped[str] = mapped_column(String(80), default="cuautoreview", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_dataset_workspace_name"),)


class DatasetShare(Base):
    """Additive workspace/user/team grants for dataset and revision access."""

    __tablename__ = "dataset_shares"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # workspace, user, team
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False, default="viewer")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        CheckConstraint(
            "(target_type = 'workspace' AND target_id IS NULL) OR (target_type IN ('user','team') AND target_id IS "
            "NOT NULL)",
            name="ck_dataset_share_target",
        ),
        UniqueConstraint("dataset_id", "target_type", "target_id", name="uq_dataset_share_target"),
    )


class ObjectArchive(Base):
    """Soft archive state for datasets, task definitions, and runs (batches)."""

    __tablename__ = "object_archives"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    object_type: Mapped[str] = mapped_column(String(24), nullable=False)
    object_id: Mapped[str] = mapped_column(String(36), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    archived_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("object_type", "object_id", name="uq_object_archive"),)


class TaskDefinition(Base):
    __tablename__ = "task_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    current_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("dataset_id", "task_id", name="uq_task_definition_dataset_id"),)


class TaskRevision(Base):
    __tablename__ = "task_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    task_definition_id: Mapped[str] = mapped_column(
        ForeignKey("task_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_revision: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("task_definition_id", "revision", name="uq_task_revision_number"),
        UniqueConstraint("task_definition_id", "source_revision", name="uq_task_source_revision"),
    )


class Preset(Base):
    __tablename__ = "presets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_preset_workspace_name"),)


class PresetRevision(Base):
    __tablename__ = "preset_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    preset_id: Mapped[str] = mapped_column(ForeignKey("presets.id", ondelete="CASCADE"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    backend: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    reasoning: Mapped[str] = mapped_column(String(32), default="low", nullable=False)
    budget_usd: Mapped[float | None] = mapped_column(nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("preset_id", "revision", name="uq_preset_revision_number"),)


class ProviderModelCatalog(Base):
    """Secret-free snapshot of model IDs discovered from provider metadata APIs."""

    __tablename__ = "provider_model_catalog"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    backend: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    models: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    preset_revision_id: Mapped[str] = mapped_column(ForeignKey("preset_revisions.id"), nullable=False)
    taxonomy_release_id: Mapped[str | None] = mapped_column(ForeignKey("taxonomy_releases.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RunSource(Base):
    """Additional datasets covered by a run; Batch.dataset_id remains its legacy primary source."""

    __tablename__ = "run_sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("batch_id", "dataset_id", name="uq_run_source_dataset"),)


class RunConfiguration(Base):
    """Immutable workflow and execution snapshots associated with a run/batch."""

    __tablename__ = "run_configurations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    workflow_revision_id: Mapped[str] = mapped_column(String(160), nullable=False)
    workflow_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    execution_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rerun_of_batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SyncWave(Base):
    __tablename__ = "sync_waves"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    sync_key: Mapped[str] = mapped_column(String(200), nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("batch_id", "number", name="uq_wave_number"),
        UniqueConstraint("batch_id", "sync_key", name="uq_wave_sync_key"),
    )


class BatchMember(Base):
    __tablename__ = "batch_members"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    task_definition_id: Mapped[str] = mapped_column(ForeignKey("task_definitions.id"), nullable=False, index=True)
    task_revision_id: Mapped[str] = mapped_column(ForeignKey("task_revisions.id"), nullable=False, index=True)
    wave_id: Mapped[str] = mapped_column(ForeignKey("sync_waves.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(160), nullable=False)
    review_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_review", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("batch_id", "task_revision_id", name="uq_batch_member_revision"),)


class BatchGrant(Base):
    __tablename__ = "batch_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        CheckConstraint("(user_id IS NOT NULL) != (team_id IS NOT NULL)", name="ck_grant_one_target"),
        UniqueConstraint("batch_id", "user_id", "role", name="uq_user_batch_role"),
        UniqueConstraint("batch_id", "team_id", "role", name="uq_team_batch_role"),
    )


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id", ondelete="CASCADE"), nullable=False, index=True)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("batch_members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(32), default="review", nullable=False)
    review_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    preset_revision_id: Mapped[str] = mapped_column(ForeignKey("preset_revisions.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    fence_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    shared_labels_snapshot: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_jobs_batch_stage_status", "batch_id", "stage", "status"),)


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    fence_token: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("job_id", "attempt_number", name="uq_job_attempt_number"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False, index=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    relay_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    relay_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("job_id", "generation", name="uq_outbox_job_generation"),)


class ReviewResult(Base):
    __tablename__ = "review_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("batch_members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    review_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    backend: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    review: Mapped[dict] = mapped_column(JSON, nullable=False)
    artifact_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("member_id", "revision", name="uq_review_member_revision"),)


class TaskFeedback(Base):
    __tablename__ = "task_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    member_id: Mapped[str] = mapped_column(
        ForeignKey("batch_members.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    step_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    episode_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    object_type: Mapped[str] = mapped_column(String(80), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class TaxonomyRelease(Base):
    __tablename__ = "taxonomy_releases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("workspace_id", "version", name="uq_taxonomy_release_version"),)


class TaxonomyProposal(Base):
    __tablename__ = "taxonomy_proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    label_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    base_release_id: Mapped[str | None] = mapped_column(ForeignKey("taxonomy_releases.id"), nullable=True)
    base_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    latest_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProposalRevision(Base):
    __tablename__ = "proposal_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("taxonomy_proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_revision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    change_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("proposal_id", "revision", name="uq_proposal_revision_number"),)


class ProposalFeedback(Base):
    __tablename__ = "proposal_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("taxonomy_proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposal_revision_id: Mapped[str] = mapped_column(ForeignKey("proposal_revisions.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TaxonomyCandidate(Base):
    __tablename__ = "taxonomy_candidates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    base_release_id: Mapped[str | None] = mapped_column(ForeignKey("taxonomy_releases.id"), nullable=True)
    base_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_heads: Mapped[dict] = mapped_column(JSON, nullable=False)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CandidateDecision(Base):
    __tablename__ = "candidate_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("taxonomy_candidates.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class StoredArtifact(Base):
    __tablename__ = "stored_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    task_revision_id: Mapped[str | None] = mapped_column(ForeignKey("task_revisions.id"), nullable=True, index=True)
    member_id: Mapped[str | None] = mapped_column(ForeignKey("batch_members.id"), nullable=True, index=True)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("member_id", "relative_path", name="uq_member_artifact_path"),)
