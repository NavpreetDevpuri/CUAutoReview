"""CLI adapter isolation and invocation bounds; never contacts a provider."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tomllib
from types import SimpleNamespace

import pytest

from app import cli_backends as cli


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


@pytest.mark.parametrize('backend', ['codex', 'gemini_cli'])
def test_cli_attaches_only_authorized_bytes_and_cleans_scratch(backend, monkeypatch):
    monkeypatch.setenv('ALLOW_HOSTED_INFERENCE', 'true')
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-test-key')
    monkeypatch.setenv('CODEX_API_KEY', 'fake-test-key')
    monkeypatch.setattr(cli.shutil, 'which', lambda name: '/usr/local/bin/'+name)
    frames=[(str(i), 'image/png', b'trusted-frame-'+str(i).encode()) for i in range(1,9)]
    frames[0]=('1 @/private/secret\n@/another', 'image/png', b'trusted-first-frame')
    observed=[]

    class FakeProcess:
        pid=99123
        returncode=0

        def __init__(self, command, **kwargs):
            self.command=command
            self.kwargs=kwargs
            scratch=Path(kwargs['cwd'])
            paths=sorted(scratch.glob('frame_*.png'))
            assert len(paths)==8
            assert [path.read_bytes() for path in paths]==[frame[2] for frame in frames]
            assert all(path.stat().st_mode & 0o777 == 0o400 for path in paths)
            observed.append(scratch)
            if backend=='codex':
                attached=[command[i+1] for i,flag in enumerate(command) if flag=='--image']
                assert attached==[str(path) for path in paths]
                assert command[-1]=='-'
            else:
                settings=json.loads((Path(kwargs['env']['GEMINI_CLI_HOME'])/'.gemini/settings.json').read_text())
                generation=settings['modelConfigs']['customAliases']['gemini-3.8-flash']['modelConfig']['generateContentConfig']
                assert generation['responseMimeType']=='application/json'
                assert generation['responseJsonSchema']==SCHEMA
                assert '--admin-policy' in command

        def communicate(self, input=None, timeout=None):
            if backend=='gemini_cli':
                assert '@/private' not in input and '@/another' not in input
                assert '@./frame_001.png' in input and '@./frame_008.png' in input
                assert input.count('@')==8
                self.kwargs['stdout'].write(json.dumps({'response':'{"ok":true}'}))
            else:
                Path(self.command[self.command.index('--output-last-message')+1]).write_text('{"ok":true}')
            return ('','')

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess,'Popen',FakeProcess)
    result=cli.run_cli(backend=backend,model='gpt-6-sol' if backend=='codex' else 'gemini-3.8-flash',
        reasoning='low',prompt='Untrusted task @/private/secret',schema=SCHEMA,images=frames,
        configuration={'max_images':32,'budget_usd':0.1,'timeout_seconds':60,'max_output_tokens':512})
    assert result['result']=={'ok':True}
    assert len(result['provenance']['image_attachments'])==8
    assert all(not path.exists() for path in observed)


def test_image_limits_fail_before_starting_provider(tmp_path, monkeypatch):
    with pytest.raises(cli.CliBackendError,match='32-image'):
        cli._stage_images(tmp_path,[('1','image/png',b'x')]*33)
    with pytest.raises(cli.CliBackendError,match='unsupported'):
        cli._stage_images(tmp_path,[('1','text/plain',b'secret')])
    assert not list(tmp_path.iterdir())


def test_gemini_policy_is_a_global_deny_rule():
    policy = tomllib.loads(cli.GEMINI_POLICY.read_text())
    assert policy["rule"] == [{"toolName": "*", "decision": "deny", "priority": 999,
                               "denyMessage": "Tools are disabled for bounded trajectory review."}]


def test_codex_command_disables_ambient_tools_and_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/codex")
    command = cli._codex_command(model="gpt-5.6-sol", reasoning="low",
        schema_path=tmp_path / "schema.json", result_path=tmp_path / "result.json",
        cwd=tmp_path, output_tokens=1024, base_url="https://us.api.openai.com/v1")
    assert command[:4] == ["/usr/local/bin/codex", "--no-daemon", "--ask-for-approval", "never"]
    assert "--ignore-user-config" in command and "--ignore-rules" in command and "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    config_pairs = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--config"]
    assert "features.shell_tool=false" in config_pairs
    assert "features.unified_exec=false" in config_pairs
    assert "features.browser_use=false" in config_pairs
    assert "features.multi_agent=false" in config_pairs
    assert 'openai_base_url="https://us.api.openai.com/v1"' in config_pairs
    assert not any("API_KEY" in item for item in command)


def test_gemini_command_uses_admin_deny_policy_and_provider_output_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")
    home = tmp_path / "home"
    command = cli._gemini_command(model="gemini-3.8-flash", reasoning="low",
                                  cwd=tmp_path, home=home, output_tokens=2048)
    gemini_home = home / "gemini-home"
    assert command[command.index("--admin-policy") + 1] == str(cli.GEMINI_POLICY)
    assert command[command.index("--approval-mode") + 1] == "default"
    assert "--skip-trust" in command
    assert "--yolo" not in command
    settings = json.loads((gemini_home / ".gemini" / "settings.json").read_text())
    alias = settings["modelConfigs"]["customAliases"]["gemini-3.8-flash"]["modelConfig"]
    assert settings["model"]["maxSessionTurns"] == 1
    assert alias["model"] == "gemini-3.8-flash"
    assert alias["generateContentConfig"]["maxOutputTokens"] == 2048
    assert alias["generateContentConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}


@pytest.mark.parametrize("url", ["https://api.openai.com/v1", "https://us.api.openai.com/v1"])
def test_codex_base_url_allows_only_official_openai_endpoints(url):
    assert cli._validated_codex_base_url(url) == url


@pytest.mark.parametrize("url", ["https://attacker.example/v1", "https://api.openai.com/v1?key=leak",
                                  "http://api.openai.com/v1", "https://api.openai.com.evil.test/v1"])
def test_codex_base_url_rejects_unapproved_endpoints(url):
    with pytest.raises(cli.CliBackendError, match="approved OpenAI endpoints"):
        cli._validated_codex_base_url(url)


def test_codex_server_default_uses_allowlisted_region_and_run_override_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/codex")
    monkeypatch.setenv("CUAUTOREVIEW_CODEX_BASE_URL", "https://us.api.openai.com/v1")
    command_args = {"model": "gpt-6-sol", "reasoning": "low", "schema_path": tmp_path / "schema.json",
        "result_path": tmp_path / "result.json", "cwd": tmp_path, "output_tokens": 1024}

    def configured_url(command):
        config_pairs = [command[i + 1] for i, value in enumerate(command[:-1]) if value == "--config"]
        return next(item.split("=", 1)[1] for item in config_pairs if item.startswith("openai_base_url="))

    assert configured_url(cli._codex_command(**command_args)) == '"https://us.api.openai.com/v1"'
    assert configured_url(cli._codex_command(**command_args, base_url="https://api.openai.com/v1")) == '"https://api.openai.com/v1"'


def test_structured_response_parses_one_json_fence_and_validates_schema():
    response, diagnostics = cli._parse_structured_response('```json\n{"ok":true}\n```', SCHEMA, "fake-key")
    assert response == {"ok": True}
    assert diagnostics == {}


def test_structured_response_failure_retains_bounded_redacted_excerpt():
    response, diagnostics = cli._parse_structured_response(
        '```json\n{"ok": true,, "api_key":"private-key"}\n```', SCHEMA, "private-key")
    assert response is None
    assert diagnostics["cli_diagnostic_category"] == "model_response_invalid_json"
    assert "private-key" not in diagnostics["cli_response_excerpt"]
    assert len(diagnostics["cli_response_excerpt"]) <= 400


def test_structured_response_schema_failure_has_safe_category():
    response, diagnostics = cli._parse_structured_response('{"ok":"wrong"}', SCHEMA, "fake-key")
    assert response is None
    assert diagnostics["cli_diagnostic_category"] == "model_response_schema_invalid"


def test_limits_reject_image_and_cost_estimate_overflow():
    with pytest.raises(cli.CliBackendError, match="image limit"):
        cli._limits({"max_images": 33})
    with pytest.raises(cli.CliBackendError, match="cost estimate"):
        cli._limits({"budget_usd": 0.51})
    with pytest.raises(cli.CliBackendError, match="timeout"):
        cli._limits({"timeout_seconds": 121})


def test_child_environment_contains_only_one_provider_key(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-pass-to-gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-secret")
    monkeypatch.setenv("DATABASE_URL", "do-not-pass-db")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "do-not-pass-google-file")
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "scratch"
    cwd.mkdir()
    codex_env = cli._clean_env(cwd=cwd, home=home, provider="codex", key="codex-test-secret")
    assert set(codex_env) == {"PATH", "HOME", "TMPDIR", "LANG", "CODEX_HOME", "CODEX_API_KEY"}
    assert codex_env["CODEX_API_KEY"] == "codex-test-secret"
    assert Path(codex_env["CODEX_HOME"]).is_dir()
    assert "OPENAI_API_KEY" not in codex_env
    gemini_env = cli._clean_env(cwd=cwd, home=home, provider="gemini_cli", key="gemini-test-secret")
    assert set(gemini_env) == {"PATH", "HOME", "TMPDIR", "LANG", "GEMINI_API_KEY",
                               "GEMINI_CLI_HOME", "GEMINI_CLI_SYSTEM_DEFAULTS_PATH",
                               "GEMINI_CLI_SYSTEM_SETTINGS_PATH"}
    assert gemini_env["GEMINI_API_KEY"] == "gemini-test-secret"
    assert Path(gemini_env["GEMINI_CLI_SYSTEM_DEFAULTS_PATH"]).is_file()
    assert Path(gemini_env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"]).is_file()
    assert "DATABASE_URL" not in gemini_env and "GOOGLE_APPLICATION_CREDENTIALS" not in gemini_env


def test_gemini_one_shot_records_soft_budget_and_parses_response(monkeypatch):
    monkeypatch.setenv("ALLOW_HOSTED_INFERENCE", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")
    calls = []

    class FakeProcess:
        pid = 90001
        returncode = 0

        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs
            settings_path = Path(kwargs["env"]["GEMINI_CLI_HOME"]) / ".gemini" / "settings.json"
            calls.append((command, kwargs, json.loads(settings_path.read_text())))

        def communicate(self, input=None, timeout=None):
            self.kwargs["stdout"].write(json.dumps({"response": json.dumps({"ok": True}),
                "stats": {"input_tokens": 120, "output_tokens": 30}}))
            assert input == "safe prompt"
            assert timeout == 90
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    output = cli.run_cli(backend="gemini_cli", model="gemini-3.8-flash", reasoning="low",
        prompt="safe prompt", schema=SCHEMA,
        configuration={"budget_usd": 0.5, "timeout_seconds": 90,
                       "max_output_tokens": 512, "max_images": 0})
    assert len(calls) == 1
    command, kwargs, settings = calls[0]
    assert "--admin-policy" in command
    assert command[command.index("--model") + 1] == "gemini-3.8-flash"
    assert command[command.index("--prompt") + 1] == ""
    assert kwargs["env"]["GEMINI_API_KEY"] == "gemini-test-secret"
    assert set(kwargs["env"]).issubset({"PATH", "HOME", "TMPDIR", "LANG", "GEMINI_API_KEY",
        "GEMINI_CLI_HOME", "GEMINI_CLI_SYSTEM_DEFAULTS_PATH", "GEMINI_CLI_SYSTEM_SETTINGS_PATH"})
    assert output["result"] == {"ok": True}
    assert output["usage"]["input_tokens"] == 120
    assert output["usage"]["invocations"] == 1
    assert output["usage"]["automatic_retries"] == 0
    assert output["usage"]["retry_policy_scope"] == "adapter_attempt"
    assert output["usage"]["budget_kind"] == "estimate_only"
    assert output["usage"]["budget_enforced"] is False
    assert output["usage"]["billed"] is True
    assert output["usage"]["output_token_limit_enforced"] is False
    assert output["usage"]["output_token_limit_setting_configured"] is True
    assert "uncached input rate" in output["usage"]["estimated_cost_assumption"]
    assert output["usage"]["timeout_enforced"] is True
    alias = settings["modelConfigs"]["customAliases"]["gemini-3.8-flash"]["modelConfig"]
    assert alias["model"] == "gemini-3.8-flash"
    assert alias["generateContentConfig"]["maxOutputTokens"] == 512
    assert alias["generateContentConfig"]["thinkingConfig"] == {"thinkingLevel": "LOW"}


def test_codex_one_shot_has_only_api_key_in_child_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "codex-test-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-pass-to-codex")
    monkeypatch.setenv("DATABASE_URL", "do-not-pass-db")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/codex")
    calls = []

    class FakeProcess:
        pid = 90002
        returncode = 0

        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs
            calls.append((command, kwargs))

        def communicate(self, input=None, timeout=None):
            output_path = Path(self.command[self.command.index("--output-last-message") + 1])
            output_path.write_text('{"ok":true}')
            self.kwargs["stdout"].write(json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 25}}) + "\n")
            assert input == "safe prompt"
            assert timeout == 60
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    output = cli.run_cli(backend="codex", model="gpt-5.6-sol", reasoning="low",
        prompt="safe prompt", schema=SCHEMA,
        configuration={"budget_usd": 0.5, "timeout_seconds": 60,
                       "max_output_tokens": 512, "max_images": 0})
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert "--ignore-user-config" in command and "--ignore-rules" in command
    assert kwargs["env"]["CODEX_API_KEY"] == "codex-test-secret"
    assert "OPENAI_API_KEY" not in kwargs["env"] and "GEMINI_API_KEY" not in kwargs["env"]
    assert "DATABASE_URL" not in kwargs["env"]
    assert output["result"] == {"ok": True}
    assert output["usage"]["input_tokens"] == 100
    assert output["usage"]["output_tokens"] == 25
    assert output["usage"]["billed"] is True
    assert output["usage"]["output_token_limit_enforced"] is False
    assert output["provenance"]["automatic_retries"] == 0
    assert output["provenance"]["retry_policy_scope"] == "adapter_attempt"


def test_codex_recoverable_error_event_does_not_discard_completed_review(monkeypatch):
    monkeypatch.setenv("CODEX_API_KEY", "codex-test-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/codex")

    class ReconnectedCodexProcess:
        pid = 90008
        returncode = 0

        def __init__(self, command, **kwargs):
            self.command = command
            self.kwargs = kwargs

        def communicate(self, input=None, timeout=None):
            result_path = Path(self.command[self.command.index("--output-last-message") + 1])
            result_path.write_text('{"ok":true}')
            events = [
                {"type": "error", "message": "Websocket reconnected; continuing turn"},
                {"type": "turn.completed", "usage": {"input_tokens": 100,
                    "cached_input_tokens": 0, "output_tokens": 25}},
            ]
            self.kwargs["stdout"].write("\n".join(json.dumps(event) for event in events))
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", ReconnectedCodexProcess)
    output = cli.run_cli(backend="codex", model="gpt-6-sol", reasoning="low",
        prompt="safe prompt", schema=SCHEMA,
        configuration={"timeout_seconds": 60, "max_output_tokens": 512, "max_images": 0})
    assert output["result"] == {"ok": True}
    assert output["usage"]["input_tokens"] == 100


def test_timeout_terminates_the_process_group(monkeypatch):
    seen = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: seen.append((pid, sig)))

    class Process:
        pid = 90003
        def __init__(self): self.calls = 0
        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("codex", timeout)
        def poll(self): return -9

    cli._terminate(Process())
    assert seen == [(90003, signal.SIGTERM), (90003, signal.SIGKILL)]


def test_gemini_usage_parses_nested_per_model_tokens_and_sums_models():
    usage = cli._gemini_usage({"models": {
        "gemini-3.8-flash": {"tokens": {"input": 120, "candidates": 30, "thoughts": 4, "cached": 10, "total": 154}},
        "gemini-3.8-pro": {"tokens": {"input": 20, "candidates": 5, "thoughts": 2, "cached": 2, "total": 29}},
    }})
    assert usage == {"input_tokens": 140, "cached_input_tokens": 12, "output_tokens": 41,
                     "reasoning_output_tokens": 6}


def test_gemini_usage_reads_flat_provider_candidates_and_thoughts():
    usage = cli._gemini_usage({"promptTokenCount": 100, "candidatesTokenCount": 20,
                               "thoughtsTokenCount": 5, "totalTokenCount": 125})
    assert usage == {"input_tokens": 100, "cached_input_tokens": None, "output_tokens": 25,
                     "reasoning_output_tokens": 5}


def test_unknown_usage_does_not_claim_a_bill_and_reported_zero_is_unbilled():
    assert cli._billed_status({"input_tokens": None, "cached_input_tokens": None,
                               "output_tokens": None}) is None
    assert cli._billed_status({"input_tokens": 0, "cached_input_tokens": 0,
                               "output_tokens": 0}) is False
    assert cli._billed_status({"input_tokens": 100, "cached_input_tokens": 100,
                               "output_tokens": 0}) is True


def test_cost_estimate_prices_all_input_at_uncached_rate(monkeypatch):
    import sys
    seen = {}
    def cost_per_token(**kwargs):
        seen.update(kwargs)
        return 0.01, 0.02
    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(cost_per_token=cost_per_token))
    estimate = cli._estimated_cost("gemini_cli", "gemini-2.5-flash", {
        "input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 10,
    })
    assert estimate == 0.03
    assert seen["prompt_tokens"] == 100
    assert seen["completion_tokens"] == 10


def test_failed_cli_without_usage_keeps_billing_unknown(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")

    class FailedProcess:
        pid = 90004
        returncode = 1

        def __init__(self, command, **kwargs):
            self.kwargs = kwargs

        def communicate(self, input=None, timeout=None):
            self.kwargs["stdout"].write(json.dumps({"response": "{}"}))
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FailedProcess)
    with pytest.raises(cli.CliBackendError) as exc:
        cli.run_cli(backend="gemini_cli", model="gemini-2.5-flash", reasoning="low",
            prompt="safe prompt", schema=SCHEMA,
            configuration={"timeout_seconds": 60, "max_output_tokens": 512, "max_images": 0})
    assert exc.value.usage["billed"] is None
    assert exc.value.usage["estimated_usd"] is None


def test_stderr_is_categorized_without_retaining_raw_details():
    assert cli._stderr_category("Error finding Codex home: CODEX_HOME points to a missing path") == "codex_home_unavailable"
    assert cli._stderr_category("Policy file error: priority must be <= 999") == "gemini_admin_policy_invalid"
    assert cli._stderr_category("HTTP 401 unauthorized") == "provider_auth_failed"
    assert cli._stderr_category("") is None


def test_safe_diagnostic_redacts_credentials_and_query_values():
    secret = "gemini-test-secret"
    message = (f"HTTP 403 permission denied for {secret}; api_key={secret}; "
               "Bearer bearer-secret at https://provider.example/path?key=url-secret&x=y "
               "and wss://provider.example/socket?token=websocket-secret\nretry")
    safe = cli._safe_diagnostic_message(message, secret)
    assert len(safe) <= 400
    assert "gemini-test-secret" not in safe
    assert "bearer-secret" not in safe
    assert "url-secret" not in safe
    assert "websocket-secret" not in safe
    assert "HTTP 403 permission denied" in safe
    assert cli._diagnostic_status(message) == 403


def test_event_diagnostic_reads_top_level_error_message_and_code():
    event = {"type": "error", "code": 403,
             "message": "permission denied at wss://provider.example/socket?key=private"}
    message = cli._event_diagnostic([event])
    assert "403" in message
    assert "permission denied" in message
    safe = cli._safe_diagnostic_message(message, "not-the-key")
    assert "private" not in safe
    assert "wss://provider.example/socket?[REDACTED_QUERY]" in safe


def test_gemini_error_report_extracts_only_error_fields(tmp_path):
    path = tmp_path / "gemini-client-error-test.json"
    path.write_text(json.dumps({"request": {"prompt": "private prompt"},
        "error": {"status": "PERMISSION_DENIED", "code": 403,
                  "message": "HTTP 403 permission denied"}}))
    result = cli._gemini_error_report(tmp_path)
    assert "HTTP 403 permission denied" in result
    assert "PERMISSION_DENIED" in result
    assert "private prompt" not in result


@pytest.mark.parametrize("cli_output, expected_category, expected_message", [
    ("not-json", "cli_output_invalid_json", "stdout did not contain valid JSON"),
    (json.dumps({"response": "not-json"}), "model_response_invalid_json", "Model response was not valid JSON"),
])
def test_gemini_outer_and_model_json_errors_are_distinguished(
        monkeypatch, cli_output, expected_category, expected_message):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")

    class FailedJsonProcess:
        pid = 90005
        returncode = 0

        def __init__(self, command, **kwargs):
            self.kwargs = kwargs

        def communicate(self, input=None, timeout=None):
            self.kwargs["stdout"].write(cli_output)
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FailedJsonProcess)
    with pytest.raises(cli.CliBackendError) as exc:
        cli.run_cli(backend="gemini_cli", model="gemini-2.5-flash", reasoning="low",
            prompt="safe prompt", schema=SCHEMA,
            configuration={"timeout_seconds": 60, "max_output_tokens": 512, "max_images": 0})
    assert exc.value.usage["cli_diagnostic_category"] == expected_category
    assert expected_message in exc.value.usage["cli_diagnostic_message"]
    assert "gemini-test-secret" not in json.dumps(exc.value.usage)


def test_codex_turn_failure_keeps_only_sanitized_diagnostic(monkeypatch):
    secret = "codex-test-secret"
    monkeypatch.setenv("CODEX_API_KEY", secret)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/codex")

    class FailedCodexProcess:
        pid = 90006
        returncode = 1

        def __init__(self, command, **kwargs):
            self.kwargs = kwargs

        def communicate(self, input=None, timeout=None):
            event = {"type": "turn.failed", "error": {"code": 403,
                "message": f"HTTP 403 permission denied for {secret} at "
                           "https://provider.example/?key=url-secret"}}
            self.kwargs["stdout"].write(json.dumps(event) + "\n")
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FailedCodexProcess)
    with pytest.raises(cli.CliBackendError) as exc:
        cli.run_cli(backend="codex", model="gpt-5.6-sol", reasoning="low",
            prompt="safe prompt", schema=SCHEMA,
            configuration={"timeout_seconds": 60, "max_output_tokens": 512, "max_images": 0})
    usage = exc.value.usage
    assert usage["cli_diagnostic_category"] == "provider_access_denied"
    assert usage["cli_diagnostic_status"] == 403
    assert "HTTP 403 permission denied" in usage["cli_diagnostic_message"]
    serialized = json.dumps(usage)
    assert secret not in serialized and "url-secret" not in serialized


def test_gemini_provider_error_report_is_converted_to_safe_usage(monkeypatch):
    secret = "gemini-test-secret"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")

    class FailedGeminiProcess:
        pid = 90007
        returncode = 1

        def __init__(self, command, **kwargs):
            self.kwargs = kwargs

        def communicate(self, input=None, timeout=None):
            report = {"error": {"status": "PERMISSION_DENIED", "code": 403,
                "message": f"HTTP 403 permission denied for {secret} at "
                           "https://provider.example/?key=url-secret"}}
            (Path(self.kwargs["cwd"]) / "gemini-client-error-test.json").write_text(json.dumps(report))
            self.kwargs["stdout"].write(json.dumps({"response": "", "error": "request failed"}))
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FailedGeminiProcess)
    with pytest.raises(cli.CliBackendError) as exc:
        cli.run_cli(backend="gemini_cli", model="gemini-2.5-flash", reasoning="low",
            prompt="safe prompt", schema=SCHEMA,
            configuration={"timeout_seconds": 60, "max_output_tokens": 512, "max_images": 0})
    usage = exc.value.usage
    assert usage["cli_diagnostic_category"] == "provider_access_denied"
    assert usage["cli_diagnostic_status"] == 403
    assert "HTTP 403 permission denied" in usage["cli_diagnostic_message"]
    serialized = json.dumps(usage)
    assert secret not in serialized and "url-secret" not in serialized


def test_gemini_payload_error_fields_are_included_in_safe_diagnostic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-secret")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/local/bin/gemini")

    class FailedPayloadProcess:
        pid = 90009
        returncode = 1

        def __init__(self, command, **kwargs):
            self.kwargs = kwargs

        def communicate(self, input=None, timeout=None):
            payload = {"response": "", "error": {"status": "PERMISSION_DENIED",
                "code": 403, "message": "HTTP 403 permission denied"}}
            self.kwargs["stdout"].write(json.dumps(payload))
            return ("", "")

        def poll(self):
            return self.returncode

    monkeypatch.setattr(cli.subprocess, "Popen", FailedPayloadProcess)
    with pytest.raises(cli.CliBackendError) as exc:
        cli.run_cli(backend="gemini_cli", model="gemini-3.8-flash", reasoning="low",
            prompt="safe prompt", schema=SCHEMA,
            configuration={"timeout_seconds": 60, "max_output_tokens": 512, "max_images": 0})
    usage = exc.value.usage
    assert usage["cli_diagnostic_category"] == "provider_access_denied"
    assert usage["cli_diagnostic_status"] == 403
    assert "HTTP 403 permission denied" in usage["cli_diagnostic_message"]
