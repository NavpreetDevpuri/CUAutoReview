"""Bounded ZIP dataset validation and evidence helpers.

Archives are read in memory without extraction. Validation caps the archive at
32 MiB, expanded content at 128 MiB, and decoded screenshots at 16 million
pixels; API diagnostics are capped at 100 errors and 100 warnings per response.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import posixpath
import re
import stat
import unicodedata
import warnings as python_warnings
from typing import Any
from zipfile import BadZipFile, ZipFile
from io import BytesIO

import yaml
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BatchMember, StoredArtifact, TaskRevision


MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_DIAGNOSTICS = 100
MAX_MANIFEST_NESTING = 100
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_HARMLESS_FILE_BYTES = 1024 * 1024
MAX_TASKS = 5000
MAX_TASK_RECORD_BYTES = 512 * 1024
MAX_STEPS_PER_TASK = 2000
MAX_TOTAL_STEPS = 50000

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
HARMLESS_NAMES = {"readme", "license", "notice", "copying", "contributing", ".ds_store"}


class ZipDatasetError(ValueError):
    def __init__(self, errors: list[dict[str, str]], warnings: list[dict[str, str]] | None = None):
        super().__init__(errors[0]["message"] if errors else "Invalid ZIP dataset")
        self.errors = errors[:MAX_DIAGNOSTICS]
        self.warnings = (warnings or [])[:MAX_DIAGNOSTICS]


@dataclass
class ValidatedZipDataset:
    tasks: list[dict[str, Any]]
    assets: dict[str, bytes]
    assets_by_task: dict[str, list[str]]
    warnings: list[dict[str, str]]
    summaries: list[dict[str, Any]]


class _UniqueKeySafeLoader(yaml.SafeLoader):
    def __init__(self, stream):
        super().__init__(stream)
        self._compose_depth = 0

    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not supported in dataset manifests")
        self._compose_depth += 1
        if self._compose_depth > MAX_MANIFEST_NESTING:
            self._compose_depth -= 1
            raise yaml.YAMLError(f"Manifest nesting exceeds {MAX_MANIFEST_NESTING} levels")
        try:
            return super().compose_node(parent, index)
        finally:
            self._compose_depth -= 1


def _construct_unique_mapping(loader: _UniqueKeySafeLoader, node, deep=False):
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ValueError("YAML mapping keys must be scalar values") from exc
        if duplicate:
            raise ValueError(f"Duplicate YAML mapping key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _append_diagnostic(items: list[dict[str, str]], item: dict[str, str]) -> None:
    """Keep validation work and serialized diagnostics bounded."""
    if len(items) < MAX_DIAGNOSTICS - 1:
        items.append(item)
    elif len(items) == MAX_DIAGNOSTICS - 1:
        items.append(_issue("archive", "Additional diagnostics were omitted", "diagnostics_truncated"))


def _issue(path: str, message: str, code: str) -> dict[str, str]:
    return {"path": path, "message": message, "code": code}


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON object key: {key}")
        value[key] = item
    return value


def _fail(path: str, message: str, code: str, warnings: list[dict[str, str]] | None = None):
    raise ZipDatasetError([_issue(path, message, code)], warnings)


def _canonical_member_name(name: str, *, directory: bool) -> str:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("Archive paths must be relative POSIX paths")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise ValueError("Absolute archive paths are not allowed")
    if unicodedata.normalize("NFC", name) != name:
        raise ValueError("Archive paths must use normalized Unicode")
    path = name[:-1] if directory and name.endswith("/") else name
    if len(path) > 500:
        raise ValueError("Archive paths must be at most 500 characters")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts) or posixpath.normpath(path) != path:
        raise ValueError("Archive paths may not contain empty, dot, or parent components")
    return path


def _read_member(archive: ZipFile, info, max_bytes: int) -> bytes:
    if info.file_size > max_bytes:
        raise ValueError(f"Expanded member exceeds the {max_bytes}-byte limit")
    with archive.open(info, "r") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) != info.file_size or len(data) > max_bytes:
        raise ValueError("Expanded member size does not match its ZIP directory entry")
    return data


def _is_harmless_file(path: str) -> bool:
    basename = path.rsplit("/", 1)[-1].lower()
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    suffix = "." + basename.rsplit(".", 1)[1] if "." in basename else ""
    return basename in HARMLESS_NAMES or (suffix in (".md", ".txt") and stem not in ("", "."))


def _image_content_type(path: str, data: bytes) -> str | None:
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    content_type = IMAGE_TYPES.get(suffix)
    if content_type == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return content_type
    if content_type == "image/jpeg" and data.startswith(b"\xff\xd8\xff"):
        return content_type
    if (content_type == "image/webp" and len(data) >= 12 and data[:4] == b"RIFF" and
            data[8:12] == b"WEBP"):
        return content_type
    return None


def _check_json_nesting(raw: bytes) -> None:
    """Reject excessively nested JSON before invoking the recursive decoder."""
    depth = 0
    quoted = False
    escaped = False
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                quoted = False
        elif byte == 0x22:
            quoted = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > MAX_MANIFEST_NESTING:
                raise ValueError(f"Manifest nesting exceeds {MAX_MANIFEST_NESTING} levels")
        elif byte in (0x7D, 0x5D):
            depth -= 1


def _validate_decodable_image(path: str, data: bytes) -> bool:
    """Verify format, dimensions, and a complete bounded pixel decode."""
    expected_type = _image_content_type(path, data)
    if expected_type is None:
        return False
    expected_format = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[expected_type]
    try:
        # Check dimensions before decoding so a small compressed image cannot
        # allocate an unbounded pixel buffer. verify() checks file layout;
        # load() on a fresh handle confirms that the image is actually readable.
        with python_warnings.catch_warnings():
            python_warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != expected_format:
                    return False
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                    return False
                image.verify()
            with Image.open(BytesIO(data)) as image:
                if image.format != expected_format:
                    return False
                image.load()
        return True
    except (Image.DecompressionBombError, Image.DecompressionBombWarning,
            UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return False


def _parse_manifest(raw: bytes, name: str) -> dict[str, Any]:
    try:
        if name.endswith(".json"):
            _check_json_nesting(raw)
            value = json.loads(raw, object_pairs_hook=_unique_json_object,
                               parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        else:
            value = yaml.load(raw, Loader=_UniqueKeySafeLoader)
    except (json.JSONDecodeError, yaml.YAMLError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        _fail(name, f"Manifest could not be parsed: {type(exc).__name__}", "invalid_manifest")
    if not isinstance(value, dict) or value.get("format") != "cuautoreview" or not isinstance(value.get("tasks"), list):
        _fail(name, "Manifest must contain format 'cuautoreview' and a tasks array", "invalid_schema")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        _fail(name, "Manifest values must be representable as JSON data", "invalid_schema")
    if not value["tasks"]:
        _fail(name, "Manifest must contain at least one task", "empty_tasks")
    if len(value["tasks"]) > MAX_TASKS:
        _fail(name, f"Manifest exceeds the {MAX_TASKS}-task limit", "too_many_tasks")
    return value


def validate_zip_dataset(data: bytes) -> ValidatedZipDataset:
    if len(data) > MAX_ARCHIVE_BYTES:
        _fail("archive", "ZIP archive exceeds the 32 MB limit", "archive_too_large")
    warnings: list[dict[str, str]] = []
    try:
        archive = ZipFile(BytesIO(data))
    except (BadZipFile, OSError, ValueError):
        _fail("archive", "Request body is not a valid ZIP archive", "invalid_zip")
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_ENTRIES:
            _fail("archive", f"ZIP archive exceeds the {MAX_ZIP_ENTRIES}-entry limit", "too_many_entries")
        expanded_size = sum(info.file_size for info in infos)
        if expanded_size > MAX_EXPANDED_BYTES:
            _fail("archive", "ZIP expanded size exceeds the 128 MB limit", "expanded_size_limit")

        harmless_paths = []
        image_infos = {}
        manifests = []
        seen = set()
        for info in infos:
            try:
                path = _canonical_member_name(info.filename, directory=info.is_dir())
            except ValueError as exc:
                _fail(info.filename[:300] or "archive", str(exc), "unsafe_path", warnings)
            canonical = path + ("/" if info.is_dir() else "")
            duplicate_key = path.casefold()
            if duplicate_key in seen:
                _fail(path, "ZIP contains duplicate paths", "duplicate_path", warnings)
            seen.add(duplicate_key)
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if stat.S_ISLNK(mode) or (file_type not in (0, stat.S_IFREG, stat.S_IFDIR)):
                _fail(path, "Symbolic links and special files are not allowed", "unsafe_file_type", warnings)
            if info.flag_bits & 0x1:
                _fail(path, "Encrypted ZIP members are not supported", "encrypted_member", warnings)
            if info.compress_size == 0 and info.file_size > 0:
                _fail(path, "ZIP member has an invalid compression size", "invalid_member_size", warnings)
            if info.compress_size and info.file_size / info.compress_size > 1000:
                _fail(path, "ZIP member compression ratio is too high", "suspicious_compression_ratio", warnings)
            if info.is_dir():
                continue
            if path in ("dataset.json", "dataset.yaml"):
                manifests.append(info)
            elif path.startswith("assets/"):
                suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
                if suffix not in IMAGE_TYPES:
                    _fail(path, "Only PNG, JPEG, and WebP screenshots are allowed under assets/", "unsupported_attachment", warnings)
                if info.file_size > MAX_SCREENSHOT_BYTES:
                    _fail(path, "Screenshot exceeds the 10 MB per-file limit", "screenshot_too_large", warnings)
                image_infos[path] = info
            elif _is_harmless_file(path):
                if info.file_size > MAX_HARMLESS_FILE_BYTES:
                    _fail(path, "Unused documentation file exceeds the 1 MB limit", "harmless_file_too_large", warnings)
                harmless_paths.append(path)
            else:
                _fail(path, "Only the root manifest, screenshot assets, and harmless documentation files are allowed", "unsupported_attachment", warnings)

        if len(manifests) != 1:
            _fail("archive", "ZIP must contain exactly one root dataset.json or dataset.yaml manifest", "manifest_count", warnings)
        manifest_info = manifests[0]
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            _fail(manifest_info.filename, "Manifest exceeds the 32 MB limit", "manifest_too_large", warnings)
        try:
            manifest_bytes = _read_member(archive, manifest_info, MAX_MANIFEST_BYTES)
        except (BadZipFile, OSError, RuntimeError, ValueError) as exc:
            _fail(manifest_info.filename, f"Manifest could not be read safely: {type(exc).__name__}", "invalid_manifest_member", warnings)
        manifest = _parse_manifest(manifest_bytes, manifest_info.filename)

        assets: dict[str, bytes] = {}
        for path, info in image_infos.items():
            try:
                image = _read_member(archive, info, MAX_SCREENSHOT_BYTES)
            except (BadZipFile, OSError, RuntimeError, ValueError) as exc:
                _fail(path, f"Screenshot could not be read safely: {type(exc).__name__}", "invalid_screenshot", warnings)
            if not _validate_decodable_image(path, image):
                _fail(path, f"Screenshot is corrupt, unreadable, mismatched, or exceeds {MAX_IMAGE_PIXELS} decoded pixels",
                      "invalid_image_content", warnings)
            assets[path] = image

    errors: list[dict[str, str]] = []
    tasks = []
    summaries = []
    assets_by_task: dict[str, list[str]] = {}
    seen_task_ids = set()
    total_steps = 0
    referenced_assets = set()
    for task_index, raw_task in enumerate(manifest["tasks"]):
        task_path = f"tasks[{task_index}]"
        if not isinstance(raw_task, dict):
            _append_diagnostic(errors, _issue(task_path, "Task record must be an object", "invalid_task"))
            continue
        task_record = json.loads(json.dumps(raw_task, ensure_ascii=False, allow_nan=False))
        task_id = task_record.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip() or len(task_id) > 160:
            _append_diagnostic(errors, _issue(f"{task_path}.task_id", "task_id must be a non-empty string of at most 160 characters", "invalid_task_id"))
            continue
        task_id = task_id.strip()
        task_record["task_id"] = task_id
        if task_id in seen_task_ids:
            _append_diagnostic(errors, _issue(f"{task_path}.task_id", "task_id must be unique within the archive", "duplicate_task_id"))
        seen_task_ids.add(task_id)
        for field, maximum in (("title", 2000), ("instruction", 20000)):
            value = task_record.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                _append_diagnostic(errors, _issue(f"{task_path}.{field}", f"{field} must be a non-empty string of at most {maximum} characters", "invalid_task_field"))
        outcome = task_record.get("outcome")
        if outcome is None or outcome == "unknown" or (isinstance(outcome, str) and outcome not in ("passed", "failed")):
            if outcome is not None and not isinstance(outcome, str):
                _append_diagnostic(errors, _issue(f"{task_path}.outcome", "outcome must be a string", "invalid_outcome"))
            else:
                task_record["outcome"] = "unknown"
                _append_diagnostic(warnings, _issue(f"{task_path}.outcome", "Outcome is unknown; this task will wait for manual review", "unknown_outcome"))
        elif outcome not in ("passed", "failed"):
            _append_diagnostic(errors, _issue(f"{task_path}.outcome", "outcome must be passed, failed, or unknown", "invalid_outcome"))
        elif isinstance(outcome, str) and len(outcome) > 80:
            task_record["outcome"] = "unknown"
            _append_diagnostic(warnings, _issue(f"{task_path}.outcome", "Outcome is unknown; this task will wait for manual review", "unknown_outcome"))
        source = task_record.get("source")
        if source is not None and not isinstance(source, dict):
            _append_diagnostic(errors, _issue(f"{task_path}.source", "source must be an object when provided", "invalid_source"))
        steps = task_record.get("steps")
        if not isinstance(steps, list):
            _append_diagnostic(errors, _issue(f"{task_path}.steps", "steps must be an array", "invalid_steps"))
            continue
        if len(steps) > MAX_STEPS_PER_TASK:
            _append_diagnostic(errors, _issue(f"{task_path}.steps", f"A task may contain at most {MAX_STEPS_PER_TASK} steps", "too_many_steps"))
        total_steps += len(steps)
        if total_steps > MAX_TOTAL_STEPS:
            _append_diagnostic(errors, _issue("tasks", f"Archive exceeds the {MAX_TOTAL_STEPS}-step limit", "too_many_steps"))
        ids = set()
        task_assets = []
        for step_index, step in enumerate(steps):
            step_path = f"{task_path}.steps[{step_index}]"
            if not isinstance(step, dict):
                _append_diagnostic(errors, _issue(step_path, "Step record must be an object", "invalid_step"))
                continue
            step_id = step.get("step_id")
            if not isinstance(step_id, str) or not step_id.strip() or len(step_id) > 160:
                _append_diagnostic(errors, _issue(f"{step_path}.step_id", "step_id must be a non-empty string of at most 160 characters", "invalid_step_id"))
            elif step_id.strip() in ids:
                _append_diagnostic(errors, _issue(f"{step_path}.step_id", "step_id must be unique within its task", "duplicate_step_id"))
            else:
                step_id = step_id.strip()
                ids.add(step_id)
                step["step_id"] = step_id
            refs = step.get("evidence_refs", [])
            if not isinstance(refs, list) or any(not isinstance(ref, str) or len(ref) > 500 for ref in refs):
                _append_diagnostic(errors, _issue(f"{step_path}.evidence_refs", "evidence_refs must be an array of short strings", "invalid_evidence_refs"))
            screenshot = step.get("screenshot")
            if screenshot is not None:
                if not isinstance(screenshot, str):
                    _append_diagnostic(errors, _issue(f"{step_path}.screenshot", "screenshot must be a relative asset path", "invalid_screenshot_reference"))
                else:
                    try:
                        path = _canonical_member_name(screenshot, directory=False)
                    except ValueError:
                        _append_diagnostic(errors, _issue(f"{step_path}.screenshot", "screenshot must be a safe relative POSIX path under assets/", "invalid_screenshot_reference"))
                        path = ""
                    if path and not path.startswith("assets/"):
                        _append_diagnostic(errors, _issue(f"{step_path}.screenshot", "screenshot references must stay under assets/", "invalid_screenshot_reference"))
                    elif path and path not in assets:
                        _append_diagnostic(errors, _issue(f"{step_path}.screenshot", "Referenced screenshot is missing from the ZIP archive", "missing_screenshot_asset"))
                    elif path:
                        task_assets.append(path)
                        referenced_assets.add(path)
            # Never accept client-supplied API URLs or artifact status as evidence grants.
            step.pop("screenshot_url", None)
            step.pop("artifact_status", None)
            for field in ("action", "observation", "intent"):
                value = step.get(field)
                if value is not None and (not isinstance(value, str) or len(value) > 20000):
                    _append_diagnostic(errors, _issue(f"{step_path}.{field}", f"{field} must be text of at most 20000 characters", "invalid_step_field"))
        task_record.pop("raw_url", None)
        task_record.pop("artifacts", None)
        review = task_record.get("review")
        if review is not None:
            if not isinstance(review, dict) or not isinstance(review.get("steps", []), list) or any(not isinstance(step, dict) for step in review.get("steps", [])):
                _append_diagnostic(errors, _issue(f"{task_path}.review", "review must contain an array of step records", "invalid_review"))
            elif isinstance(review.get("steps", []), list):
                for review_step in review.get("steps", []):
                    review_step.pop("screenshot_url", None)
                    review_step.pop("artifact_status", None)
        try:
            if len(json.dumps(task_record, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")) > MAX_TASK_RECORD_BYTES:
                _append_diagnostic(errors, _issue(task_path, "Task record exceeds the 512 KB limit", "task_too_large"))
        except (TypeError, ValueError):
            _append_diagnostic(errors, _issue(task_path, "Task record contains values that cannot be represented as JSON", "invalid_task_value"))
        tasks.append(task_record)
        assets_by_task[task_id] = sorted(set(task_assets))
        summaries.append({"task_id": task_id, "title": task_record.get("title") or task_id,
                          "step_count": len(steps), "outcome": task_record.get("outcome", "unknown")})
        if not task_assets:
            _append_diagnostic(warnings, _issue(f"{task_path}.steps", "No screenshot assets are attached to this task", "screenshots_absent"))

    if errors:
        raise ZipDatasetError(errors, warnings)
    for path in sorted(set(assets) - referenced_assets):
        _append_diagnostic(warnings, _issue(path, "Screenshot is not referenced by any task and will not be imported", "unused_screenshot"))
    for path in harmless_paths:
        _append_diagnostic(warnings, _issue(path, "Harmless file is unused by the dataset manifest", "unused_file"))
    return ValidatedZipDataset(tasks=tasks, assets=assets, assets_by_task=assets_by_task,
                               warnings=warnings, summaries=summaries)


def copy_revision_artifacts_to_member(db: Session, workspace_id: str, revision: TaskRevision,
                                      member: BatchMember) -> None:
    """Propagate dataset revision evidence into a batch-scoped authorization record."""
    source_rows = db.scalars(select(StoredArtifact).where(
        StoredArtifact.task_revision_id == revision.id, StoredArtifact.member_id.is_(None))).all()
    existing = set(db.scalars(select(StoredArtifact.relative_path).where(
        StoredArtifact.member_id == member.id)).all())
    existing.update(item.relative_path for item in db.new
                    if isinstance(item, StoredArtifact) and item.member_id == member.id)
    for source in source_rows:
        if source.relative_path in existing:
            continue
        db.add(StoredArtifact(workspace_id=workspace_id, task_revision_id=revision.id,
            member_id=member.id, relative_path=source.relative_path, media_type=source.media_type,
            object_key=source.object_key, sha256=source.sha256,
            source_relative_path=source.source_relative_path))
        existing.add(source.relative_path)
