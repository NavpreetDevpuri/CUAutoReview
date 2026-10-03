"""Bounded multimodal adapters for installed Codex and Gemini CLIs.

The Celery worker is a separate, non-root container. Each CLI process receives
only its provider key, runs from an empty temporary directory, and gets no host
or application environment. These limits bound the invocation and wall time;
provider billing is reported or estimated and is not a hard dollar cap.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit


class CliBackendError(RuntimeError):
    def __init__(self, message: str, *, usage: dict | None = None):
        super().__init__(message)
        self.usage = usage


# Bundled Gemini CLI policy and settings files.
RESOURCES = Path(__file__).with_name("resources")
MAX_TIMEOUT_SECONDS = 120
MAX_OUTPUT_TOKENS = 4096
MAX_BUDGET_USD = 0.50
MAX_IMAGES = 32
MAX_IMAGE_BYTES = 32 * 1024 * 1024
_IMAGE_GEMINI_POLICY = Path("/etc/cuautoreview/gemini-deny-all.toml")
GEMINI_POLICY = _IMAGE_GEMINI_POLICY if _IMAGE_GEMINI_POLICY.is_file() else RESOURCES / "gemini-deny-all.toml"
GEMINI_EMPTY_DEFAULTS = RESOURCES / "gemini-empty-defaults.json"
GEMINI_EMPTY_SETTINGS = RESOURCES / "gemini-empty-settings.json"
PINNED_CLI_VERSIONS = {"codex": "0.157.0", "gemini_cli": "0.61.0"}
CODEX_BASE_URLS = {
    "https://api.openai.com/v1",
    "https://us.api.openai.com/v1",
}
DEFAULT_CODEX_BASE_URL = "https://api.openai.com/v1"

CODEX_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "hooks",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "multi_agent",
    "memories",
    "shell_snapshot",
    "skill_search",
    "skill_mcp_dependency_install",
    "sleep_tool",
    "goals",
    "view_image",
)


def _config_value(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _validated_codex_base_url(value: object) -> str:
    """Allow only the two official OpenAI API origins before exposing the key."""
    if value is None:
        value = os.getenv("CUAUTOREVIEW_CODEX_BASE_URL") or DEFAULT_CODEX_BASE_URL
    if not isinstance(value, str) or value not in CODEX_BASE_URLS:
        raise CliBackendError("Codex API base URL must be one of the approved OpenAI endpoints.")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"api.openai.com", "us.api.openai.com"}
        or parsed.path != "/v1"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise CliBackendError("Codex API base URL must be one of the approved OpenAI endpoints.")
    return value


def _limits(configuration: dict) -> tuple[int, int]:
    timeout = int(configuration.get("timeout_seconds", 90))
    output_tokens = int(configuration.get("max_output_tokens", 2048))
    if not 15 <= timeout <= MAX_TIMEOUT_SECONDS:
        raise CliBackendError("CLI timeout must be between 15 and 120 seconds.")
    if not 256 <= output_tokens <= MAX_OUTPUT_TOKENS:
        raise CliBackendError("CLI output-token estimate must be between 256 and 4096.")
    if not 0 <= int(configuration.get("max_images", MAX_IMAGES)) <= MAX_IMAGES:
        raise CliBackendError("CLI image limit must be between 0 and 32.")
    budget = configuration.get("budget_usd")
    if budget is not None and (
        not isinstance(budget, (int, float)) or isinstance(budget, bool) or not 0 < float(budget) <= MAX_BUDGET_USD
    ):
        raise CliBackendError("The configured CLI cost estimate must be between $0 and $0.50.")
    return timeout, output_tokens


def _clean_env(*, cwd: Path, home: Path, provider: str, key: str) -> dict[str, str]:
    env = {
        "PATH": os.getenv("CUAUTOREVIEW_CLI_PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(cwd),
        "LANG": "C.UTF-8",
    }
    if provider == "codex":
        codex_home = home / "codex-home"
        codex_home.mkdir(mode=0o700, exist_ok=True)
        env["CODEX_HOME"] = str(codex_home)
        env["CODEX_API_KEY"] = key
    else:
        gemini_home = home / "gemini-home"
        gemini_home.mkdir(mode=0o700, exist_ok=True)
        env.update(
            {
                "GEMINI_API_KEY": key,
                "GEMINI_CLI_HOME": str(gemini_home),
                "GEMINI_CLI_SYSTEM_DEFAULTS_PATH": str(GEMINI_EMPTY_DEFAULTS),
                "GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(GEMINI_EMPTY_SETTINGS),
            }
        )
    return env


def _codex_command(
    *,
    model: str,
    reasoning: str,
    schema_path: Path,
    result_path: Path,
    cwd: Path,
    output_tokens: int,
    base_url: str | None = None,
    image_paths=(),
) -> list[str]:
    binary = shutil.which("codex")
    if not binary:
        raise CliBackendError("Codex CLI is unavailable in the isolated worker.")
    base_url = _validated_codex_base_url(base_url)
    command = [
        binary,
        "--no-daemon",
        "--ask-for-approval",
        "never",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--cd",
        str(cwd),
        "--model",
        model,
        "--json",
        "--color",
        "never",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(result_path),
    ]
    config = {
        "model_reasoning_effort": reasoning,
        "openai_base_url": base_url,
        "model_verbosity": "low",
        "web_search": "disabled",
        "project_doc_max_bytes": 0,
        "features.skip_host_skill_discovery": True,
    }
    config.update({f"features.{name}": False for name in CODEX_DISABLED_FEATURES})
    # The CLI has no provider-enforced output-token flag. Keep the requested
    # estimate in the prompt/provenance and rely on schema, single invocation,
    # and wall-clock termination for this adapter.
    for key, value in config.items():
        command.extend(["--config", f"{key}={_config_value(value)}"])
    for path in image_paths:
        command.extend(["--image", str(path)])
    command.append("-")
    return command


def _gemini_command(
    *, model: str, reasoning: str, cwd: Path, home: Path, output_tokens: int, schema: dict | None = None
) -> list[str]:
    binary = shutil.which("gemini")
    if not binary:
        raise CliBackendError("Gemini CLI is unavailable in the isolated worker.")
    if not GEMINI_POLICY.is_file():
        raise CliBackendError("Gemini CLI deny-all policy is missing from the worker image.")
    # Gemini model aliases let this isolated run pin the requested model and
    # the provider's maxOutputTokens setting while the visible CLI model name
    # uses the actual provider ID so countTokens resolves the same model.
    gemini_home = home / "gemini-home"
    gemini_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Gemini CLI 0.61.0 resolves its global config directory as
    # GEMINI_CLI_HOME/.gemini, even though GEMINI_CLI_HOME itself is the
    # overridden home directory. Keep the alias at the path the CLI reads.
    gemini_config_dir = gemini_home / ".gemini"
    gemini_config_dir.mkdir(mode=0o700, exist_ok=True)
    settings_path = gemini_config_dir / "settings.json"
    settings = {
        "security": {"auth": {"selectedType": "gemini-api-key"}},
        "model": {"name": model, "maxSessionTurns": 1},
        "modelConfigs": {
            "customAliases": {
                model: {
                    "modelConfig": {
                        "model": model,
                        "generateContentConfig": {
                            "maxOutputTokens": output_tokens,
                            "temperature": 0,
                            "thinkingConfig": {"thinkingLevel": "LOW" if reasoning in ("low", "minimal") else "HIGH"},
                        },
                    }
                }
            }
        },
        "privacy": {"usageStatisticsEnabled": False},
    }
    if schema is not None:
        generation = settings["modelConfigs"]["customAliases"][model]["modelConfig"]["generateContentConfig"]
        generation["responseMimeType"] = "application/json"
        generation["responseJsonSchema"] = schema
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    return [
        binary,
        "--prompt",
        "",
        "--model",
        model,
        "--output-format",
        "json",
        "--approval-mode",
        "default",
        "--skip-trust",
        "--admin-policy",
        str(GEMINI_POLICY),
    ]


def _stage_images(cwd: Path, images) -> tuple[list[Path], list[dict]]:
    """Only caller-authorized bytes enter the CLI scratch directory; never source paths."""
    if len(images) > MAX_IMAGES or sum(len(row[2]) for row in images) > MAX_IMAGE_BYTES:
        raise CliBackendError("Selected image attachments exceed the 32-image or 32 MiB limit.")
    extensions = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    paths = []
    metadata = []
    for index, (step_id, mime, data) in enumerate(images, 1):
        if mime not in extensions or not isinstance(data, bytes) or not data:
            raise CliBackendError("Screenshot attachment has an unsupported type or empty content.")
        path = cwd / f"frame_{index:03d}{extensions[mime]}"
        path.write_bytes(data)
        path.chmod(0o400)
        paths.append(path)
        metadata.append(
            {
                "step_id": str(step_id),
                "file": path.name,
                "media_type": mime,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    return paths, metadata


def _attachment_prompt(prompt: str, backend: str, metadata: list[dict]) -> str:
    # Gemini expands @paths BEFORE the model sees the untrusted source. Escape
    # every source-controlled @, then append only our generated safe filenames.
    if backend == "gemini_cli":
        prompt = prompt.replace("@", r"\u0040")
    if not metadata:
        return prompt
    lines = ["\nSCREENSHOT ATTACHMENTS IN ORDER:"]
    for index, item in enumerate(metadata, 1):
        step_label = json.dumps(str(item["step_id"]), ensure_ascii=True)
        if backend == "gemini_cli":
            step_label = step_label.replace("@", r"\u0040")
        label = f"Image {index}: source step {step_label}; frame evidence for this step."
        lines.append(label + (" @./" + item["file"] if backend == "gemini_cli" else ""))
    return prompt + "\n".join(lines)


def _codex_usage(events: list[dict]) -> dict:
    usage = {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None}
    for event in events:
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            reported = event["usage"]
            for key in usage:
                value = reported.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    usage[key] = value
    return usage


def _gemini_usage(stats: object) -> dict:
    result = {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None, "reasoning_output_tokens": None}
    if not isinstance(stats, dict):
        return result

    def first_int(values: object, names: tuple[str, ...]) -> int | None:
        if not isinstance(values, dict):
            return None
        for name in names:
            value = values.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    # Gemini CLI reports per-model metrics as stats.models[*].tokens. Sum the
    # model records because one CLI turn can make requests to multiple models.
    models = stats.get("models")
    model_records = models.values() if isinstance(models, dict) else models if isinstance(models, list) else []
    nested_input: list[int] = []
    nested_cached: list[int] = []
    nested_candidate: list[int] = []
    nested_output: list[int] = []
    nested_thoughts: list[int] = []
    aliases = {
        "input": ("input", "input_tokens", "prompt", "promptTokenCount", "prompt_tokens"),
        "cached": ("cached", "cached_input_tokens", "cachedContentTokenCount", "cached_tokens"),
        "candidate": ("candidates", "candidatesTokenCount", "responseTokenCount"),
        "output": ("output", "output_tokens", "response", "completion_tokens"),
        "thoughts": ("thoughts", "thoughtsTokenCount", "reasoning_output_tokens"),
    }
    for record in model_records:
        if not isinstance(record, dict):
            continue
        token_metrics = record.get("tokens")
        for key, target in (
            ("input", nested_input),
            ("cached", nested_cached),
            ("candidate", nested_candidate),
            ("output", nested_output),
            ("thoughts", nested_thoughts),
        ):
            value = first_int(token_metrics, aliases[key])
            if value is not None:
                target.append(value)
    if nested_input:
        result["input_tokens"] = sum(nested_input)
    if nested_cached:
        result["cached_input_tokens"] = sum(nested_cached)
    if nested_candidate or nested_output:
        result["output_tokens"] = sum(nested_candidate or nested_output) + sum(nested_thoughts)
    if nested_thoughts:
        result["reasoning_output_tokens"] = sum(nested_thoughts)

    # Keep compatibility with flat stats formats used by earlier CLI builds.
    flat_aliases = {
        "input_tokens": aliases["input"],
        "cached_input_tokens": aliases["cached"],
        "reasoning_output_tokens": aliases["thoughts"],
    }
    for key, names in flat_aliases.items():
        if result[key] is None:
            result[key] = first_int(stats, names)
    if result["output_tokens"] is None:
        candidate = first_int(stats, aliases["candidate"])
        output = first_int(stats, aliases["output"])
        thoughts = result["reasoning_output_tokens"] or 0
        if candidate is not None or output is not None or thoughts:
            result["output_tokens"] = (candidate if candidate is not None else output or 0) + thoughts
    return result


def _billed_status(usage: dict) -> bool | None:
    """Only assert billing when provider usage contains billable token evidence."""
    values = [usage.get(name) for name in ("input_tokens", "cached_input_tokens", "output_tokens")]
    known = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    if any(value > 0 for value in known):
        return True
    if len(known) == len(values):
        return False
    return None


def _stderr_category(stderr: str) -> str | None:
    """Classify CLI setup/provider failures without retaining raw stderr."""
    message = stderr.lower()
    if not message.strip():
        return None
    if "codex_home points to" in message or "error finding codex home" in message:
        return "codex_home_unavailable"
    if "priority must be <= 999" in message or "policy file error" in message:
        return "gemini_admin_policy_invalid"
    if "skipping system settings file" in message or "parent directory" in message and "insecure" in message:
        return "gemini_settings_not_root_owned"
    if "not running in a trusted directory" in message or "gemini_cli_trust_workspace" in message:
        return "workspace_not_trusted"
    if any(
        marker in message
        for marker in ("invalid api key", "api key not valid", "unauthorized", "http 401", "status 401")
    ):
        return "provider_auth_failed"
    if any(marker in message for marker in ("permission_denied", "permission denied", "http 403", "status 403")):
        return "provider_access_denied"
    if any(
        marker in message for marker in ("resource_exhausted", "quota exceeded", "rate limit", "http 429", "status 429")
    ):
        return "provider_quota_or_rate_limit"
    if any(marker in message for marker in ("invalid_argument", "bad request", "http 400", "status 400")):
        return "provider_request_rejected"
    if any(marker in message for marker in ("model not found", "unsupported model", "unknown model")):
        return "provider_model_unavailable"
    if any(marker in message for marker in ("http 5", "status 5", "internal server error", "service unavailable")):
        return "provider_upstream_error"
    return "cli_stderr_unclassified"


def _diagnostic_status(stderr: str) -> int | None:
    for pattern in (
        r'"code"\s*:\s*(\d{3})',
        r"\bHTTP(?: error)?\s*[:=]?\s*(\d{3})",
        r"\bstatus(?:_code)?\s*[:= ]+\s*(\d{3})",
    ):
        match = re.search(pattern, stderr, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _diagnostic_category(message: str, *, backend: str) -> str | None:
    """Classify sanitized provider/CLI text without storing its raw source."""
    category = _stderr_category(message)
    if category:
        return category
    if not message.strip():
        return None
    return "codex_turn_failed" if backend == "codex" else "gemini_turn_failed"


def _safe_diagnostic_message(message: str, key: str) -> str | None:
    """Keep a short actionable CLI error while redacting credentials and URL queries."""
    if not message.strip():
        return None
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", message)
    value = value.replace(key, "[REDACTED_KEY]")
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", value)
    value = re.sub(
        r'(?i)\b(api[_ -]?key|access[_ -]?token|secret)\s*[:=]\s*["\']?[^\s,;}"\']+', r"\1=[REDACTED]", value
    )
    value = re.sub(r"(?i)\b(?:AIza)[A-Za-z0-9_-]{20,}", "[REDACTED_KEY]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}", "[REDACTED_KEY]", value)
    value = re.sub(
        r"(?:https?|wss?)://[^\s?]+\?[^\s]+", lambda match: match.group(0).split("?", 1)[0] + "?[REDACTED_QUERY]", value
    )
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s{2,}", " ", value).strip()
    return value[:400]


def unwrap_json_fence(text: str) -> str:
    """Remove exactly one outer JSON code fence; leave all other text untouched."""
    value = text.strip()
    match = re.fullmatch(r"```(?:json)?[ \t]*\r?\n?(.*?)\r?\n?```", value, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else value


def _parse_structured_response(text: str, schema: dict, key: str) -> tuple[dict | None, dict]:
    """Parse a strict JSON response and retain only a redacted bounded failure excerpt."""
    value = unwrap_json_fence(text)
    evidence = {
        "cli_response_length": len(text),
        "cli_response_excerpt": _safe_diagnostic_message(text[:240], key),
    }
    try:
        response = json.loads(value)
    except json.JSONDecodeError as exc:
        excerpt = value[max(0, exc.pos - 80) : min(len(value), exc.pos + 120)]
        safe_excerpt = _safe_diagnostic_message(excerpt, key)
        info = {
            "cli_diagnostic_category": "model_response_invalid_json",
            "cli_diagnostic_message": (
                f"Model response was not valid JSON at line {exc.lineno}, "
                f"column {exc.colno} ({exc.msg}): {safe_excerpt or '[empty response]'}"
            ),
            **evidence,
        }
        return None, info
    try:
        import jsonschema

        jsonschema.validate(response, schema)
    except Exception as exc:
        # Do not persist validator messages that may quote a response value.
        validator = getattr(exc, "validator", None)
        pointer = getattr(exc, "json_path", None)
        detail = f" ({validator} at {pointer})" if isinstance(validator, str) and isinstance(pointer, str) else ""
        info = {
            "cli_diagnostic_category": "model_response_schema_invalid",
            "cli_diagnostic_message": f"Model response JSON failed schema validation{detail}.",
            **evidence,
        }
        return None, info
    return response, {}


def _event_diagnostic(events: list[dict]) -> str:
    messages = []
    for event in events:
        if event.get("type") not in ("error", "turn.failed"):
            continue
        error = event.get("error")
        if isinstance(error, str):
            messages.append(error)
        elif isinstance(error, dict):
            messages.extend(
                str(error[key]) for key in ("code", "type", "message") if isinstance(error.get(key), (str, int))
            )
        messages.extend(
            str(event[key]) for key in ("code", "type", "message") if isinstance(event.get(key), (str, int))
        )
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "error" and isinstance(item.get("message"), str):
            messages.append(item["message"])
    return " ".join(messages)


def _gemini_error_report(cwd: Path) -> str:
    """Extract only error/status fields from Gemini's temporary diagnostic JSON."""
    messages = []
    for path in cwd.glob("gemini-client-error-*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        def visit(value: object, depth: int = 0) -> None:
            if depth > 8:
                return
            if isinstance(value, dict):
                for name, child in value.items():
                    if name.lower() in ("message", "status", "code", "reason", "type") and isinstance(
                        child, (str, int)
                    ):
                        messages.append(str(child))
                    elif isinstance(child, (dict, list)):
                        visit(child, depth + 1)
            elif isinstance(value, list):
                for child in value[:30]:
                    visit(child, depth + 1)

        visit(data)
    return " ".join(messages)


def _estimated_cost(backend: str, model: str, usage: dict) -> float | None:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    try:
        import litellm

        model_name = model if backend == "codex" else f"gemini/{model}"
        input_cost, output_cost = litellm.cost_per_token(
            model=model_name,
            # Price all input at the uncached rate. Cached-token discounts are
            # deliberately omitted, so this estimate is an upper bound when
            # input_tokens includes the cached subset reported by the CLI.
            prompt_tokens=max(0, input_tokens),
            completion_tokens=output_tokens,
        )
        return round(float(input_cost + output_cost), 8)
    except Exception:
        return None


def terminate_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        pass


def run_cli(
    *, backend: str, model: str, reasoning: str, prompt: str, schema: dict, configuration: dict, images=()
) -> dict:
    """Execute one CLI request and return parsed JSON plus usage/provenance."""
    if backend not in ("codex", "gemini_cli"):
        raise CliBackendError("Unsupported CLI backend.")
    timeout, output_tokens = _limits(configuration)
    key = (
        (os.getenv("CODEX_API_KEY") or os.getenv("OPENAI_API_KEY"))
        if backend == "codex"
        else os.getenv("GEMINI_API_KEY")
    )
    if not key:
        required = "an invocation-scoped Codex API key" if backend == "codex" else "GEMINI_API_KEY"
        raise CliBackendError(f"{required} is unavailable to the isolated worker.")
    binary_name = "codex" if backend == "codex" else "gemini"
    if not shutil.which(binary_name):
        raise CliBackendError(f"{binary_name} CLI is unavailable in the isolated worker.")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cu-review-cli-") as raw:
        root = Path(raw)
        cwd = root / "scratch"
        home = root / "home"
        cwd.mkdir(mode=0o700)
        home.mkdir(mode=0o700)
        schema_path = root / "review-schema.json"
        result_path = root / "last-message.json"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        image_paths, image_metadata = _stage_images(cwd, images)
        if len(image_paths) > int(configuration.get("max_images", MAX_IMAGES)):
            raise CliBackendError("Screenshot attachment count exceeds the configured image limit.")
        prompt = _attachment_prompt(prompt, backend, image_metadata)
        if backend == "codex":
            codex_base_url = _validated_codex_base_url(configuration.get("codex_base_url"))
            command = _codex_command(
                model=model,
                reasoning=reasoning,
                schema_path=schema_path,
                result_path=result_path,
                cwd=cwd,
                output_tokens=output_tokens,
                base_url=codex_base_url,
                image_paths=image_paths,
            )
        else:
            command = _gemini_command(
                model=model, reasoning=reasoning, cwd=cwd, home=home, output_tokens=output_tokens, schema=schema
            )
        env = _clean_env(cwd=cwd, home=home, provider=backend, key=key)
        with (
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout,
            tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stderr,
        ):
            usage = {"input_tokens": None, "cached_input_tokens": None, "output_tokens": None}
            if backend == "gemini_cli":
                usage["reasoning_output_tokens"] = None
            response_diagnostics: dict = {}
            response = None
            error = None
            diagnostic_category = None
            diagnostic_status = None
            diagnostic_message = None
            events: list[dict] = []
            try:
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.PIPE,
                    stdout=stdout,
                    stderr=stderr,
                    text=True,
                    start_new_session=True,
                )
                try:
                    process.communicate(prompt, timeout=timeout)
                except subprocess.TimeoutExpired:
                    terminate_process_group(process)
                    process.communicate()
                    error = f"CLI wall-clock limit of {timeout} seconds was reached."
                    diagnostic_category = "cli_timeout"
                    diagnostic_message = f"CLI exceeded the {timeout}-second wall-clock limit."
                stdout.seek(0)
                stdout_text = stdout.read()
                stderr.seek(0)
                stderr_text = stderr.read(32768)
                if backend == "codex":
                    for line in stdout_text.splitlines():
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            events.append(event)
                    usage = _codex_usage(events)
                    # A wall-clock timeout keeps its own diagnosis; later output checks do not replace it.
                    if not error and any(event.get("type") == "turn.failed" for event in events):
                        error = "Codex CLI reported a failed turn."
                        event_message = _event_diagnostic(events)
                        diagnostic_category = _diagnostic_category(
                            " ".join((event_message, stderr_text)), backend=backend
                        )
                        diagnostic_status = _diagnostic_status(" ".join((event_message, stderr_text)))
                        diagnostic_message = _safe_diagnostic_message(event_message or stderr_text, key)
                    if not error and process.returncode == 0 and result_path.is_file():
                        try:
                            response_text = result_path.read_text(encoding="utf-8")
                        except OSError:
                            response_text = ""
                            error = "Codex CLI output file could not be read."
                            diagnostic_category = "model_response_missing"
                            diagnostic_message = "Codex CLI did not create a readable structured output file."
                        if not error:
                            response, response_diagnostics = _parse_structured_response(response_text, schema, key)
                            if response_diagnostics:
                                error = "Codex CLI returned invalid structured output."
                                diagnostic_category = response_diagnostics["cli_diagnostic_category"]
                                diagnostic_message = response_diagnostics["cli_diagnostic_message"]
                else:
                    try:
                        payload = json.loads(stdout_text)
                    except json.JSONDecodeError:
                        payload = None
                        # Empty stdout after a timeout is expected; keep the timeout diagnosis.
                        if not error:
                            error = "Gemini CLI returned invalid JSON."
                            report_message = _gemini_error_report(cwd)
                            combined = " ".join((report_message, stderr_text))
                            diagnostic_category = (
                                _diagnostic_category(combined, backend=backend)
                                if combined.strip()
                                else "cli_output_invalid_json"
                            )
                            diagnostic_status = _diagnostic_status(combined)
                            diagnostic_message = _safe_diagnostic_message(report_message or stderr_text, key)
                            if not diagnostic_message and diagnostic_category == "cli_output_invalid_json":
                                diagnostic_message = "Gemini CLI stdout did not contain valid JSON."
                    if isinstance(payload, dict):
                        usage = _gemini_usage(payload.get("stats"))
                        if not error and payload.get("error"):
                            error = "Gemini CLI reported a failed turn."
                            payload_error_message = _event_diagnostic(
                                [{"type": "error", "error": payload.get("error")}]
                            )
                            report_message = _gemini_error_report(cwd)
                            combined = " ".join((payload_error_message, report_message, stderr_text))
                            diagnostic_category = _diagnostic_category(combined, backend=backend)
                            diagnostic_status = _diagnostic_status(combined)
                            diagnostic_message = _safe_diagnostic_message(
                                report_message or payload_error_message or stderr_text, key
                            )
                        elif not error:
                            response_text = payload.get("response")
                            if isinstance(response_text, str):
                                response, response_diagnostics = _parse_structured_response(response_text, schema, key)
                                if response_diagnostics:
                                    error = "Gemini CLI returned invalid structured output."
                                    diagnostic_category = response_diagnostics["cli_diagnostic_category"]
                                    diagnostic_message = response_diagnostics["cli_diagnostic_message"]
                if not error and process.returncode != 0:
                    error = f"{binary_name} CLI exited with status {process.returncode}."
                    if backend == "codex":
                        event_message = _event_diagnostic(events)
                        combined = " ".join((event_message, stderr_text))
                    else:
                        combined = stderr_text
                    diagnostic_category = (
                        diagnostic_category or _diagnostic_category(combined, backend=backend) or "cli_exit_nonzero"
                    )
                    diagnostic_status = diagnostic_status or _diagnostic_status(combined) or process.returncode
                    diagnostic_message = diagnostic_message or _safe_diagnostic_message(combined, key)
                if not error and not isinstance(response, dict):
                    error = f"{binary_name} CLI returned no structured review."
                    event_message = _event_diagnostic(events) if backend == "codex" else ""
                    diagnostic_category = (
                        _diagnostic_category(event_message, backend=backend) or "model_response_missing"
                    )
                    diagnostic_status = _diagnostic_status(event_message)
                    diagnostic_message = (
                        _safe_diagnostic_message(event_message, key)
                        or "The CLI completed without a structured review response."
                    )
                if error:
                    raise CliBackendError(
                        error,
                        usage={
                            **usage,
                            "kind": "provider_reported_or_unknown",
                            "estimated_usd": _estimated_cost(backend, model, usage),
                            "estimated_cost_assumption": "all input tokens priced at the uncached input rate; "
                            "cached-token discounts omitted",
                            "billed": _billed_status(usage),
                            "cli_diagnostic_category": diagnostic_category,
                            "cli_diagnostic_status": diagnostic_status,
                            "cli_diagnostic_message": diagnostic_message,
                            **response_diagnostics,
                            "budget_kind": "estimate_only",
                            "budget_enforced": False,
                            "invocations": 1,
                            "automatic_retries": 0,
                            "retry_policy_scope": "adapter_attempt",
                            "duration_ms": round((time.monotonic() - started) * 1000),
                        },
                    )
            except CliBackendError:
                raise
            except (OSError, subprocess.SubprocessError) as exc:
                raise CliBackendError(
                    f"{binary_name} CLI could not complete ({type(exc).__name__}).",
                    usage={
                        **usage,
                        "kind": "unknown",
                        "estimated_usd": None,
                        "billed": None,
                        "budget_kind": "estimate_only",
                        "budget_enforced": False,
                        "invocations": 1,
                        "automatic_retries": 0,
                        "retry_policy_scope": "adapter_attempt",
                    },
                ) from None
            finally:
                if "process" in locals() and process.poll() is None:
                    terminate_process_group(process)
    estimated = _estimated_cost(backend, model, usage)
    return {
        "result": response,
        "usage": {
            **usage,
            "kind": "provider_reported_tokens" if any(v is not None for v in usage.values()) else "unknown",
            "estimated_usd": estimated,
            "estimated_cost_assumption": "all input tokens priced at the uncached input rate; cached-token discounts "
            "omitted",
            "billed": _billed_status(usage),
            "budget_usd": configuration.get("budget_usd"),
            "budget_kind": "estimate_only",
            "budget_enforced": False,
            "timeout_seconds": timeout,
            "timeout_enforced": True,
            "max_output_tokens": output_tokens,
            "output_token_limit_enforced": False,
            "output_token_limit_setting_configured": backend == "gemini_cli",
            "invocations": 1,
            "automatic_retries": 0,
            "retry_policy_scope": "adapter_attempt",
        },
        "provenance": {
            "backend": backend,
            "requested_model": model,
            "cli_version": PINNED_CLI_VERSIONS[backend],
            "requested_reasoning": reasoning,
            "reasoning_applied": True,
            "image_attachments": image_metadata,
            "attachment_transport": "codex_initial_images" if backend == "codex" else "gemini_at_file_inline_data",
            "new_inference": True,
            "invocations": 1,
            "automatic_retries": 0,
            "retry_policy_scope": "adapter_attempt",
            "timeout_seconds": timeout,
            "timeout_enforced": True,
            "budget_usd": configuration.get("budget_usd"),
            "budget_kind": "estimate_only",
            "budget_enforced": False,
            "output_token_limit_enforced": False,
            "output_token_limit_setting_configured": backend == "gemini_cli",
            "isolation": "dedicated worker container, temporary HOME and empty scratch directory",
            "cost_estimate_assumption": "all input tokens priced at the uncached input rate; cached-token discounts "
            "omitted",
            "note": "One CLI invocation per job attempt with a wall-clock timeout; the job retry policy determines "
            "additional attempts. The provider CLI may reconnect internally, and those network attempts are "
            "not counted by this adapter. Billing is not a hard cap.",
        },
    }
