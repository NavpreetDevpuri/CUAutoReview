"""Regression tests for adapter timeout, fenced-output and subprocess isolation handling."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from app import cli_backends as cli
from app import review_backends as review
from app.taxonomy_backend import consolidate_drafts
from test_adapters import fake_provider, fixture_task


def gemini_timeout(monkeypatch, stderr_text):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")
    monkeypatch.setattr(os, "killpg", lambda pid, sig: None)

    class TimedOutProcess:
        pid, returncode = 90010, -15

        def __init__(self, command, **kwargs):
            self.kwargs, self.calls = kwargs, 0

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                self.kwargs["stderr"].write(stderr_text)
                raise subprocess.TimeoutExpired("gemini", timeout)
            return "", ""

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", TimedOutProcess)
    with pytest.raises(cli.CliBackendError) as error:
        cli.run_cli(backend="gemini_cli", model="gemini-3.8-flash", reasoning="low", prompt="p",
                    schema={"type": "object"}, configuration={"budget_usd": 0.1, "timeout_seconds": 15,
                                                               "max_images": 0})
    return error.value


@pytest.mark.parametrize("stderr_text", ["", "(node:12) [DEP0040] DeprecationWarning: punycode is deprecated.\n"])
def test_gemini_timeout_keeps_retryable_timeout_category(monkeypatch, stderr_text):
    from app.queue import _retryable_failure

    error = gemini_timeout(monkeypatch, stderr_text)
    assert "wall-clock limit" in str(error)
    assert error.usage["cli_diagnostic_category"] == "cli_timeout"
    assert _retryable_failure(review.ReviewBackendError(str(error), usage=error.usage))


def test_model_api_accepts_one_fenced_json_block(monkeypatch):
    fake_provider(monkeypatch, "```json\n{}\n```")
    with pytest.raises(review.ReviewBackendError) as error:
        review.execute_review(backend="model_api", preset_revision={
            "model": "test", "budget_usd": 1, "configuration": {"max_images": 0}},
            task_snapshot=fixture_task(), review_kind="failure_analysis")
    # The fence was removed and the JSON parsed; the empty object then fails review validation.
    assert "failed validation" in str(error.value)

    fake_provider(monkeypatch, "not json")
    with pytest.raises(review.ReviewBackendError) as error:
        review.execute_review(backend="model_api", preset_revision={
            "model": "test", "budget_usd": 1, "configuration": {"max_images": 0}},
            task_snapshot=fixture_task(), review_kind="failure_analysis")
    assert "invalid JSON" in str(error.value) and "No automatic retry" not in str(error.value)


def test_taxonomy_curation_accepts_one_fenced_json_block(monkeypatch):
    _, calls = fake_provider(monkeypatch, '```json\n{"labels": [], "mappings": [], "unresolved": []}\n```')
    output = consolidate_drafts(preset_revision={"backend": "model_api", "model": "test", "budget_usd": 1},
                                base_content={"labels": []}, proposals=[])
    assert len(calls) == 1 and output["content"]["labels"] == []


def claude_run(monkeypatch, communicate):
    monkeypatch.setenv("ALLOW_HOSTED_INFERENCE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key")
    for name, value in {"DATABASE_URL": "postgresql://secret", "AWS_SECRET_ACCESS_KEY": "s3-secret",
                        "OPENAI_API_KEY": "openai-secret"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(review.shutil, "which", lambda name: "/usr/local/bin/claude")
    killed = []
    monkeypatch.setattr(cli.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    seen = {}

    class Process:
        pid, returncode = 90020, 0

        def __init__(self, command, **kwargs):
            seen.update(kwargs)
            self.calls = 0

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            return communicate(self.calls, timeout)

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(review.subprocess, "Popen", Process)
    with pytest.raises(review.ReviewBackendError) as error:
        review.execute_review(backend="claude_code", preset_revision={"model": "claude-test", "budget_usd": 1},
                              task_snapshot=fixture_task(), review_kind="failure_analysis")
    return seen, killed, error.value


def test_claude_adapter_gets_only_allowlisted_environment(monkeypatch):
    seen, _, _ = claude_run(monkeypatch, lambda call, timeout: (json.dumps({"structured_output": {}}), ""))
    assert set(seen["env"]) == {"PATH", "HOME", "TMPDIR", "LANG", "ANTHROPIC_API_KEY",
                                "CLAUDE_CODE_MAX_OUTPUT_TOKENS"}
    assert seen["env"]["ANTHROPIC_API_KEY"] == "anthropic-test-key"
    assert seen["start_new_session"] is True


def test_claude_adapter_timeout_kills_process_group(monkeypatch):
    def communicate(call, timeout):
        if call == 1:
            raise subprocess.TimeoutExpired("claude", timeout)
        return "", ""

    _, killed, error = claude_run(monkeypatch, communicate)
    assert killed and killed[0][0] == 90020
    assert "timed out" in str(error)
