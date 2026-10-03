"""Initial schema: every table, constraint and index of the platform before versioned migrations.

Databases created earlier by ``Base.metadata.create_all`` match this revision and are adopted by
``app.core.migrate`` (stamped, not recreated).

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "provider_model_catalog",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("backend", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("source", sa.String(length=160), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("models", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "backend"),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_team_workspace_name"),
    )
    op.create_index(op.f("ix_teams_workspace_id"), "teams", ["workspace_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_workspace_id"), "users", ["workspace_id"], unique=False)
    op.create_table(
        "activity_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("object_type", sa.String(length=80), nullable=False),
        sa.Column("object_id", sa.String(length=160), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_activity_events_actor_id"), "activity_events", ["actor_id"], unique=False)
    op.create_index(op.f("ix_activity_events_created_at"), "activity_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_activity_events_workspace_id"), "activity_events", ["workspace_id"], unique=False)
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_adapter", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_dataset_workspace_name"),
    )
    op.create_index(op.f("ix_datasets_workspace_id"), "datasets", ["workspace_id"], unique=False)
    op.create_table(
        "object_archives",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("object_type", sa.String(length=24), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by", sa.String(length=36), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["archived_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_type", "object_id", name="uq_object_archive"),
    )
    op.create_index(op.f("ix_object_archives_archived_at"), "object_archives", ["archived_at"], unique=False)
    op.create_index(op.f("ix_object_archives_workspace_id"), "object_archives", ["workspace_id"], unique=False)
    op.create_table(
        "presets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_preset_workspace_name"),
    )
    op.create_index(op.f("ix_presets_workspace_id"), "presets", ["workspace_id"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "taxonomy_releases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "version", name="uq_taxonomy_release_version"),
    )
    op.create_index(op.f("ix_taxonomy_releases_workspace_id"), "taxonomy_releases", ["workspace_id"], unique=False)
    op.create_table(
        "team_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("team_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )
    op.create_index(op.f("ix_team_members_team_id"), "team_members", ["team_id"], unique=False)
    op.create_index(op.f("ix_team_members_user_id"), "team_members", ["user_id"], unique=False)
    op.create_table(
        "dataset_shares",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(target_type = 'workspace' AND target_id IS NULL) OR "
            "(target_type IN ('user','team') AND target_id IS NOT NULL)",
            name="ck_dataset_share_target",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "target_type", "target_id", name="uq_dataset_share_target"),
    )
    op.create_index(op.f("ix_dataset_shares_dataset_id"), "dataset_shares", ["dataset_id"], unique=False)
    op.create_index(op.f("ix_dataset_shares_workspace_id"), "dataset_shares", ["workspace_id"], unique=False)
    op.create_table(
        "preset_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("preset_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("reasoning", sa.String(length=32), nullable=False),
        sa.Column("budget_usd", sa.Float(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["preset_id"], ["presets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("preset_id", "revision", name="uq_preset_revision_number"),
    )
    op.create_index(op.f("ix_preset_revisions_preset_id"), "preset_revisions", ["preset_id"], unique=False)
    op.create_table(
        "task_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=160), nullable=False),
        sa.Column("current_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "task_id", name="uq_task_definition_dataset_id"),
    )
    op.create_index(op.f("ix_task_definitions_dataset_id"), "task_definitions", ["dataset_id"], unique=False)
    op.create_table(
        "taxonomy_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("base_release_id", sa.String(length=36), nullable=True),
        sa.Column("base_hash", sa.String(length=64), nullable=False),
        sa.Column("proposal_heads", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["base_release_id"],
            ["taxonomy_releases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_taxonomy_candidates_workspace_id"), "taxonomy_candidates", ["workspace_id"], unique=False)
    op.create_table(
        "taxonomy_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("label_id", sa.String(length=120), nullable=True),
        sa.Column("base_release_id", sa.String(length=36), nullable=True),
        sa.Column("base_hash", sa.String(length=64), nullable=False),
        sa.Column("latest_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["base_release_id"],
            ["taxonomy_releases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_taxonomy_proposals_workspace_id"), "taxonomy_proposals", ["workspace_id"], unique=False)
    op.create_table(
        "batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("preset_revision_id", sa.String(length=36), nullable=False),
        sa.Column("taxonomy_release_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["preset_revision_id"],
            ["preset_revisions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_release_id"],
            ["taxonomy_releases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batches_dataset_id"), "batches", ["dataset_id"], unique=False)
    op.create_index(op.f("ix_batches_workspace_id"), "batches", ["workspace_id"], unique=False)
    op.create_table(
        "candidate_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("expected_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["taxonomy_candidates.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_candidate_decisions_candidate_id"), "candidate_decisions", ["candidate_id"], unique=False)
    op.create_table(
        "proposal_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("base_revision_hash", sa.String(length=64), nullable=True),
        sa.Column("change_type", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["taxonomy_proposals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "revision", name="uq_proposal_revision_number"),
    )
    op.create_index(op.f("ix_proposal_revisions_proposal_id"), "proposal_revisions", ["proposal_id"], unique=False)
    op.create_table(
        "task_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_definition_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_revision", sa.String(length=64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_definition_id"], ["task_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_definition_id", "revision", name="uq_task_revision_number"),
        sa.UniqueConstraint("task_definition_id", "source_revision", name="uq_task_source_revision"),
    )
    op.create_index(op.f("ix_task_revisions_source_revision"), "task_revisions", ["source_revision"], unique=False)
    op.create_index(
        op.f("ix_task_revisions_task_definition_id"), "task_revisions", ["task_definition_id"], unique=False
    )
    op.create_table(
        "batch_grants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("team_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(user_id IS NOT NULL) != (team_id IS NOT NULL)", name="ck_grant_one_target"),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "team_id", "role", name="uq_team_batch_role"),
        sa.UniqueConstraint("batch_id", "user_id", "role", name="uq_user_batch_role"),
    )
    op.create_index(op.f("ix_batch_grants_batch_id"), "batch_grants", ["batch_id"], unique=False)
    op.create_index(op.f("ix_batch_grants_team_id"), "batch_grants", ["team_id"], unique=False)
    op.create_index(op.f("ix_batch_grants_user_id"), "batch_grants", ["user_id"], unique=False)
    op.create_table(
        "proposal_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("proposal_revision_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["proposal_id"], ["taxonomy_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposal_revision_id"],
            ["proposal_revisions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_proposal_feedback_proposal_id"), "proposal_feedback", ["proposal_id"], unique=False)
    op.create_index(
        op.f("ix_proposal_feedback_proposal_revision_id"), "proposal_feedback", ["proposal_revision_id"], unique=False
    )
    op.create_table(
        "run_configurations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_revision_id", sa.String(length=160), nullable=False),
        sa.Column("workflow_snapshot", sa.JSON(), nullable=False),
        sa.Column("execution_snapshot", sa.JSON(), nullable=False),
        sa.Column("rerun_of_batch_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["rerun_of_batch_id"],
            ["batches.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_run_configurations_batch_id"), "run_configurations", ["batch_id"], unique=True)
    op.create_table(
        "run_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "dataset_id", name="uq_run_source_dataset"),
    )
    op.create_index(op.f("ix_run_sources_batch_id"), "run_sources", ["batch_id"], unique=False)
    op.create_index(op.f("ix_run_sources_dataset_id"), "run_sources", ["dataset_id"], unique=False)
    op.create_table(
        "sync_waves",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("sync_key", sa.String(length=200), nullable=False),
        sa.Column("task_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "number", name="uq_wave_number"),
        sa.UniqueConstraint("batch_id", "sync_key", name="uq_wave_sync_key"),
    )
    op.create_index(op.f("ix_sync_waves_batch_id"), "sync_waves", ["batch_id"], unique=False)
    op.create_table(
        "batch_members",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("task_definition_id", sa.String(length=36), nullable=False),
        sa.Column("task_revision_id", sa.String(length=36), nullable=False),
        sa.Column("wave_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=160), nullable=False),
        sa.Column("review_kind", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_definition_id"],
            ["task_definitions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_revision_id"],
            ["task_revisions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["wave_id"],
            ["sync_waves.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "task_revision_id", name="uq_batch_member_revision"),
    )
    op.create_index(op.f("ix_batch_members_batch_id"), "batch_members", ["batch_id"], unique=False)
    op.create_index(op.f("ix_batch_members_task_definition_id"), "batch_members", ["task_definition_id"], unique=False)
    op.create_index(op.f("ix_batch_members_task_revision_id"), "batch_members", ["task_revision_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("review_kind", sa.String(length=32), nullable=False),
        sa.Column("preset_revision_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fence_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("shared_labels_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["batch_members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["preset_revision_id"],
            ["preset_revisions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(op.f("ix_jobs_available_at"), "jobs", ["available_at"], unique=False)
    op.create_index(op.f("ix_jobs_batch_id"), "jobs", ["batch_id"], unique=False)
    op.create_index("ix_jobs_batch_stage_status", "jobs", ["batch_id", "stage", "status"], unique=False)
    op.create_index(op.f("ix_jobs_lease_expires_at"), "jobs", ["lease_expires_at"], unique=False)
    op.create_index(op.f("ix_jobs_member_id"), "jobs", ["member_id"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(op.f("ix_jobs_workspace_id"), "jobs", ["workspace_id"], unique=False)
    op.create_table(
        "stored_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_revision_id", sa.String(length=36), nullable=True),
        sa.Column("member_id", sa.String(length=36), nullable=True),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("source_relative_path", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["batch_members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_revision_id"],
            ["task_revisions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "relative_path", name="uq_member_artifact_path"),
    )
    op.create_index(op.f("ix_stored_artifacts_member_id"), "stored_artifacts", ["member_id"], unique=False)
    op.create_index(
        op.f("ix_stored_artifacts_task_revision_id"), "stored_artifacts", ["task_revision_id"], unique=False
    )
    op.create_index(op.f("ix_stored_artifacts_workspace_id"), "stored_artifacts", ["workspace_id"], unique=False)
    op.create_table(
        "task_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("step_id", sa.String(length=160), nullable=True),
        sa.Column("episode_id", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["member_id"], ["batch_members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_feedback_member_id"), "task_feedback", ["member_id"], unique=False)
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("fence_token", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_job_attempt_number"),
    )
    op.create_index(op.f("ix_job_attempts_job_id"), "job_attempts", ["job_id"], unique=False)
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("relay_owner", sa.String(length=160), nullable=True),
        sa.Column("relay_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_attempts", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "generation", name="uq_outbox_job_generation"),
    )
    op.create_index(op.f("ix_outbox_events_available_at"), "outbox_events", ["available_at"], unique=False)
    op.create_index(op.f("ix_outbox_events_job_id"), "outbox_events", ["job_id"], unique=False)
    op.create_index(op.f("ix_outbox_events_status"), "outbox_events", ["status"], unique=False)
    op.create_table(
        "review_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("member_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("review_kind", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=8), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("backend", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("review", sa.JSON(), nullable=False),
        sa.Column("artifact_key", sa.String(length=512), nullable=True),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.ForeignKeyConstraint(["member_id"], ["batch_members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "revision", name="uq_review_member_revision"),
    )
    op.create_index(op.f("ix_review_results_job_id"), "review_results", ["job_id"], unique=False)
    op.create_index(op.f("ix_review_results_member_id"), "review_results", ["member_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_review_results_member_id"), table_name="review_results")
    op.drop_index(op.f("ix_review_results_job_id"), table_name="review_results")
    op.drop_table("review_results")
    op.drop_index(op.f("ix_outbox_events_status"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_job_id"), table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_available_at"), table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index(op.f("ix_job_attempts_job_id"), table_name="job_attempts")
    op.drop_table("job_attempts")
    op.drop_index(op.f("ix_task_feedback_member_id"), table_name="task_feedback")
    op.drop_table("task_feedback")
    op.drop_index(op.f("ix_stored_artifacts_workspace_id"), table_name="stored_artifacts")
    op.drop_index(op.f("ix_stored_artifacts_task_revision_id"), table_name="stored_artifacts")
    op.drop_index(op.f("ix_stored_artifacts_member_id"), table_name="stored_artifacts")
    op.drop_table("stored_artifacts")
    op.drop_index(op.f("ix_jobs_workspace_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_member_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_lease_expires_at"), table_name="jobs")
    op.drop_index("ix_jobs_batch_stage_status", table_name="jobs")
    op.drop_index(op.f("ix_jobs_batch_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_available_at"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_batch_members_task_revision_id"), table_name="batch_members")
    op.drop_index(op.f("ix_batch_members_task_definition_id"), table_name="batch_members")
    op.drop_index(op.f("ix_batch_members_batch_id"), table_name="batch_members")
    op.drop_table("batch_members")
    op.drop_index(op.f("ix_sync_waves_batch_id"), table_name="sync_waves")
    op.drop_table("sync_waves")
    op.drop_index(op.f("ix_run_sources_dataset_id"), table_name="run_sources")
    op.drop_index(op.f("ix_run_sources_batch_id"), table_name="run_sources")
    op.drop_table("run_sources")
    op.drop_index(op.f("ix_run_configurations_batch_id"), table_name="run_configurations")
    op.drop_table("run_configurations")
    op.drop_index(op.f("ix_proposal_feedback_proposal_revision_id"), table_name="proposal_feedback")
    op.drop_index(op.f("ix_proposal_feedback_proposal_id"), table_name="proposal_feedback")
    op.drop_table("proposal_feedback")
    op.drop_index(op.f("ix_batch_grants_user_id"), table_name="batch_grants")
    op.drop_index(op.f("ix_batch_grants_team_id"), table_name="batch_grants")
    op.drop_index(op.f("ix_batch_grants_batch_id"), table_name="batch_grants")
    op.drop_table("batch_grants")
    op.drop_index(op.f("ix_task_revisions_task_definition_id"), table_name="task_revisions")
    op.drop_index(op.f("ix_task_revisions_source_revision"), table_name="task_revisions")
    op.drop_table("task_revisions")
    op.drop_index(op.f("ix_proposal_revisions_proposal_id"), table_name="proposal_revisions")
    op.drop_table("proposal_revisions")
    op.drop_index(op.f("ix_candidate_decisions_candidate_id"), table_name="candidate_decisions")
    op.drop_table("candidate_decisions")
    op.drop_index(op.f("ix_batches_workspace_id"), table_name="batches")
    op.drop_index(op.f("ix_batches_dataset_id"), table_name="batches")
    op.drop_table("batches")
    op.drop_index(op.f("ix_taxonomy_proposals_workspace_id"), table_name="taxonomy_proposals")
    op.drop_table("taxonomy_proposals")
    op.drop_index(op.f("ix_taxonomy_candidates_workspace_id"), table_name="taxonomy_candidates")
    op.drop_table("taxonomy_candidates")
    op.drop_index(op.f("ix_task_definitions_dataset_id"), table_name="task_definitions")
    op.drop_table("task_definitions")
    op.drop_index(op.f("ix_preset_revisions_preset_id"), table_name="preset_revisions")
    op.drop_table("preset_revisions")
    op.drop_index(op.f("ix_dataset_shares_workspace_id"), table_name="dataset_shares")
    op.drop_index(op.f("ix_dataset_shares_dataset_id"), table_name="dataset_shares")
    op.drop_table("dataset_shares")
    op.drop_index(op.f("ix_team_members_user_id"), table_name="team_members")
    op.drop_index(op.f("ix_team_members_team_id"), table_name="team_members")
    op.drop_table("team_members")
    op.drop_index(op.f("ix_taxonomy_releases_workspace_id"), table_name="taxonomy_releases")
    op.drop_table("taxonomy_releases")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_presets_workspace_id"), table_name="presets")
    op.drop_table("presets")
    op.drop_index(op.f("ix_object_archives_workspace_id"), table_name="object_archives")
    op.drop_index(op.f("ix_object_archives_archived_at"), table_name="object_archives")
    op.drop_table("object_archives")
    op.drop_index(op.f("ix_datasets_workspace_id"), table_name="datasets")
    op.drop_table("datasets")
    op.drop_index(op.f("ix_activity_events_workspace_id"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_created_at"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_actor_id"), table_name="activity_events")
    op.drop_table("activity_events")
    op.drop_index(op.f("ix_users_workspace_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_teams_workspace_id"), table_name="teams")
    op.drop_table("teams")
    op.drop_table("provider_model_catalog")
    op.drop_table("workspaces")
