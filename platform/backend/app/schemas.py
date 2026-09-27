from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Signup(InputModel):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid email address")
        return value


class Login(InputModel):
    email: str
    password: str


class TeamCreate(InputModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class TeamUpdate(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None


class AddTeamMember(InputModel):
    user_id: str


class UserUpdate(InputModel):
    active: bool | None = None
    role: Literal["admin", "manager", "reviewer", "viewer"] | None = None


class DatasetCreate(InputModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    source_adapter: str = "cuautoreview"


class DatasetImport(InputModel):
    format: Literal["cuautoreview"]
    tasks: list[dict[str, Any]] = Field(min_length=1, max_length=5000)


class DatasetUpdate(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class PresetCreate(InputModel):
    name: str = Field(min_length=1, max_length=160)
    backend: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, min_length=1, max_length=160)
    reasoning: str = "low"
    budget_usd: float | None = Field(default=None, ge=0)
    configuration: dict[str, Any] = Field(default_factory=dict)


class BatchCreate(InputModel):
    dataset_id: str
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    mode: Literal["fixed", "appendable"] = "fixed"
    preset_id: str
    task_ids: list[str] | None = Field(default=None, max_length=5000)
    team_ids: list[str] = Field(default_factory=list, max_length=500)


class RunExecution(InputModel):
    backend: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=160)
    reasoning: str = Field(default="low", max_length=32)
    budget_usd: float | None = Field(default=None, ge=0, le=0.5)
    configuration: dict[str, Any] = Field(default_factory=dict)


class ProviderModel(InputModel):
    id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    display_name: str | None = Field(default=None, max_length=120,
                                     pattern=r"^[A-Za-z0-9][A-Za-z0-9 .()+_/-]*$")
    provider: Literal["google", "openai", "anthropic"]
    recommended: bool = False
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)


class ProviderModelCatalogSync(InputModel):
    backend: Literal["model_api", "litellm", "codex", "gemini_cli", "claude_code"]
    status: Literal["available", "unavailable", "unknown"]
    source: Literal["google_models_api", "openai_models_api", "anthropic_models_api",
                    "provider_models_api", "runner_preflight"]
    fetched_at: datetime
    models: list[ProviderModel] = Field(max_length=500)


class RunCreate(InputModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    dataset_ids: list[str] | None = Field(default=None, max_length=200)
    task_definition_ids: list[str] | None = Field(default=None, max_length=5000)
    workflow_revision_id: str = Field(default="trajectory_review@1", min_length=1, max_length=160)
    execution: RunExecution
    team_ids: list[str] = Field(default_factory=list, max_length=500)
    user_ids: list[str] = Field(default_factory=list, max_length=500)


class RunConfigure(InputModel):
    workflow_revision_id: str | None = Field(default=None, min_length=1, max_length=160)
    execution: RunExecution | None = None


class RunRerun(InputModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    workflow_revision_id: str | None = Field(default=None, min_length=1, max_length=160)
    execution: RunExecution | None = None


class DatasetShareTarget(InputModel):
    target_id: str
    role: Literal["viewer", "reviewer", "manager"] = "viewer"


class DatasetSharesUpdate(InputModel):
    workspace_shared: bool = False
    users: list[DatasetShareTarget] = Field(default_factory=list, max_length=500)
    teams: list[DatasetShareTarget] = Field(default_factory=list, max_length=500)


class AnalyticsQuery(InputModel):
    dataset_ids: list[str] = Field(default_factory=list, max_length=200)
    run_ids: list[str] = Field(default_factory=list, max_length=500)
    task_definition_ids: list[str] = Field(default_factory=list, max_length=5000)
    include_archived: bool = False


class AnalyticsCompare(InputModel):
    result_ids: list[str] = Field(min_length=2, max_length=100)


class BatchGrantCreate(InputModel):
    team_id: str | None = None
    user_id: str | None = None
    role: Literal["manager", "reviewer", "viewer"]


class StartBatch(InputModel):
    confirm_budget: bool = False
    expected_budget_usd: float | None = Field(default=None, ge=0)


class TaxonomyProposalCreate(InputModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    kind: Literal["label", "edit", "merge", "retire", "new_label", "edit_label", "retire_label"] = "label"
    base_release_id: str | None = None
    label_id: str | None = None
    evidence_refs: list[Any] = Field(default_factory=list)


class FeedbackCreate(InputModel):
    text: str = Field(min_length=1, max_length=12000)
    step_id: str | None = None
    episode_id: str | None = None


class ProposalFeedback(InputModel):
    text: str = Field(min_length=1, max_length=12000)


class CandidateApproval(InputModel):
    expected_hash: str = Field(min_length=64, max_length=64)
    version: str = Field(min_length=1, max_length=40)


class CandidateRejection(InputModel):
    reason: str = Field(min_length=1, max_length=12000)


class TaxonomyConsolidate(InputModel):
    # Omitting a pinned preset always uses deterministic, no-cost consolidation.
    preset_revision_id: str | None = None
    confirm_budget: bool = False
    expected_budget_usd: float | None = Field(default=None, ge=0)
