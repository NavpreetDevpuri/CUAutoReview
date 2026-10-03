"""Prompt workflow catalog and validation of execution settings for runs and presets."""

from __future__ import annotations

import copy
import json
import os
import re
from typing import Any

from fastapi import HTTPException

from app.models import PresetRevision
from app.schemas import StartBatch


def workflow_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "trajectory_review",
            "revision_id": "trajectory_review@1",
            "name": "Trajectory review",
            "version": 1,
            "description": "Evidence-grounded review of failures and recovery in computer-use trajectories.",
            "input_contract": "A task instruction, recorded outcome, ordered steps, evidence references, and "
            "authorized screenshots.",
            "output_schema_version": "1",
            "supported_backends": ["saved_replay", "model_api", "litellm", "claude_code", "codex", "gemini_cli"],
            "stages": [
                {
                    "id": "failure_analysis",
                    "name": "Failure analysis",
                    "kind": "failure_analysis",
                    "prompt": "Explain evidence-supported mistakes that contributed to the recorded failed outcome "
                    "and any later recovery. Separate recovery from outcome contribution; do not invent "
                    "unseen intent or effects.",
                },
                {
                    "id": "pass_recovery",
                    "name": "Pass recovery",
                    "kind": "pass_recovery",
                    "prompt": "The recorded task passed. Find intermediate mistakes and subsequent recovery when "
                    "supported. Passing does not prove an error-free path; outcome contribution must be "
                    "not_applicable.",
                },
            ],
        }
    ]


def workflow_by_revision(revision_id: str) -> dict[str, Any]:
    for item in workflow_catalog():
        if revision_id in (item["revision_id"], item["id"]):
            return item
    raise HTTPException(404, "Workflow revision not found")


def validate_execution(execution: dict[str, Any]) -> dict[str, Any]:
    """Shared execution bounds for run snapshots and saved presets; returns a checked copy with defaults."""
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
    secret_keys = {
        "api_key",
        "apikey",
        "secret",
        "password",
        "token",
        "accesstoken",
        "refreshtoken",
        "credential",
        "credentials",
        "authorization",
    }

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
    return {"backend": backend, "model": model, "budget_usd": budget, "configuration": config}


def execution_snapshot(execution: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    checked = validate_execution(execution)
    backend, config = checked["backend"], checked["configuration"]
    config["workflow_snapshot"] = copy.deepcopy(workflow)
    return {
        "backend": backend,
        "model": checked["model"],
        "reasoning": execution.get("reasoning") or "low",
        "budget_usd": checked["budget_usd"],
        "budget_kind": "none" if backend == "saved_replay" else "estimate_only",
        "budget_enforced": backend == "saved_replay",
        "configuration": config,
    }


def require_preset_budget_confirmation(preset: PresetRevision, body: StartBatch | None):
    if preset.backend == "saved_replay":
        return
    if os.getenv("ALLOW_HOSTED_INFERENCE", "false").lower() != "true":
        raise HTTPException(409, "Hosted inference is disabled. Set ALLOW_HOSTED_INFERENCE=true to opt in.")
    from app.worker.review_backends import provider_capabilities

    capability_id = "model_api" if preset.backend == "litellm" else preset.backend
    capability = next((item for item in provider_capabilities() if item.get("id") == capability_id), None)
    if not capability or not capability.get("configured") or capability.get("execution_enabled") is False:
        raise HTTPException(409, "This backend is not configured and enabled on the local worker")
    if not body or not body.confirm_budget or body.expected_budget_usd != preset.budget_usd:
        raise HTTPException(409, "Confirm the pinned batch budget before starting")
