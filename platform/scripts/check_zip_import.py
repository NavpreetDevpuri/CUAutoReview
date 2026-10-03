#!/usr/bin/env python3
"""Real-service ZIP dataset acceptance checks; never starts model jobs."""
from __future__ import annotations

import datetime
import hashlib
import json
import secrets
import struct
import time
import urllib.error
import urllib.request
import zlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from e2e_local import BASE, Client, ROOT


def png_bytes(color: tuple[int, int, int]) -> bytes:
    """Create a valid 1x1 RGBA PNG using only the standard library."""
    def chunk(kind: bytes, content: bytes) -> bytes:
        checksum = zlib.crc32(kind + content) & 0xFFFFFFFF
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", checksum)

    red, green, blue = color
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(bytes((0, red, green, blue, 255)))) +
            chunk(b"IEND", b""))


def acceptance_task(task_id: str, screenshot: str) -> dict:
    return {
        "task_id": task_id,
        "title": "Acceptance ZIP screenshot fixture",
        "instruction": "Inspect the visible acceptance fixture.",
        "outcome": "passed",
        "steps": [{
            "step_id": "acceptance-step-1",
            "action": "Inspect screenshot",
            "observation": "A single colored pixel is recorded.",
            "evidence_refs": ["acceptance-zip-image"],
            "screenshot": screenshot,
        }],
    }


def archive_bytes(tasks: list[dict], image: bytes | None = None) -> bytes:
    image_path = "assets/acceptance-zip-screen.png"
    manifest = {"format": "cuautoreview", "tasks": tasks}
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("dataset.json", json.dumps(manifest, separators=(",", ":")))
        if image is not None:
            archive.writestr(image_path, image)
    return buffer.getvalue()


def zip_call(client: Client, path: str, payload: bytes, expected: int = 200):
    request = urllib.request.Request(
        BASE + "/api" + path,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/zip", "Origin": BASE},
    )
    try:
        response = client.opener.open(request, timeout=45)
    except urllib.error.HTTPError as exc:
        response = exc
    raw = response.read()
    if response.status != expected:
        detail = raw[:500].decode(errors="replace")
        raise AssertionError(f"POST {path}: expected HTTP {expected}, got {response.status}: {detail}")
    if raw and "json" in response.headers.get("Content-Type", ""):
        return json.loads(raw)
    return raw


def pass_check(name: str) -> None:
    print("PASS " + name, flush=True)


def main() -> None:
    account_path = ROOT / "platform/.local/test-account.json"
    if not account_path.is_file():
        raise RuntimeError("Missing ignored local test credentials at platform/.local/test-account.json")
    credentials = json.loads(account_path.read_text(encoding="utf-8"))
    admin = Client()
    identity = admin.call("POST", "/auth/login", {
        "email": credentials["email"], "password": credentials["password"]})
    if identity.get("role") != "admin":
        raise AssertionError("The configured local test account must be an administrator")

    suffix = str(time.time_ns())[-12:]
    image_path = "assets/acceptance-zip-screen.png"
    task_id = "acceptance-zip-" + suffix
    original_image = png_bytes((25, 90, 180))
    revised_image = png_bytes((180, 70, 35))
    assert hashlib.sha256(original_image).digest() != hashlib.sha256(revised_image).digest()

    dataset = admin.call("POST", "/datasets", {
        "name": "Acceptance ZIP import " + suffix,
        "description": "Named real-service ZIP import acceptance fixture; no inference."})
    before = admin.call("GET", f"/datasets/{dataset['id']}")
    assert before["tasks"] == []

    payload = archive_bytes([acceptance_task(task_id, image_path)], original_image)
    preview = zip_call(admin, "/imports/zip/validate", payload)
    assert preview["valid"] is True and preview["task_count"] == 1
    assert preview["screenshot_count"] == 1
    after_preview = admin.call("GET", f"/datasets/{dataset['id']}")
    assert after_preview["tasks"] == [], "ZIP preview persisted dataset tasks"
    pass_check("ZIP preview validates a screenshot without persisting task data")

    imported = zip_call(admin, f"/datasets/{dataset['id']}/import-zip", payload)
    assert imported["created"] == 1 and imported["revised"] == 0 and imported["unchanged"] == 0
    repeated = zip_call(admin, f"/datasets/{dataset['id']}/import-zip", payload)
    assert repeated["created"] == 0 and repeated["revised"] == 0 and repeated["unchanged"] == 1
    initial_task = admin.call("GET", f"/datasets/{dataset['id']}")["tasks"][0]
    initial_dataset_url = initial_task["steps"][0]["screenshot_url"]
    assert "revision_id=" + initial_task["revision_id"] in initial_dataset_url

    invalid_dataset = admin.call("POST", "/datasets", {
        "name": "Acceptance ZIP invalid atomicity " + suffix,
        "description": "Named invalid ZIP atomicity acceptance fixture."})
    partial_task = acceptance_task("acceptance-zip-partial-" + suffix, image_path)
    invalid_task = acceptance_task("", image_path)
    invalid_payload = archive_bytes([partial_task, invalid_task], original_image)
    invalid = zip_call(admin, f"/datasets/{invalid_dataset['id']}/import-zip", invalid_payload, expected=422)
    assert any(item["code"] == "invalid_task_id" for item in invalid["detail"]["errors"])
    assert admin.call("GET", f"/datasets/{invalid_dataset['id']}")["tasks"] == [], \
        "Invalid archive partially wrote task revisions"
    pass_check("Valid import is idempotent; invalid multi-task archive leaves no partial writes")

    # Existing fixture users are not needed: create two ephemeral viewer accounts.
    viewer = Client()
    viewer_identity = viewer.call("POST", "/auth/signup", {
        "name": "Acceptance ZIP reviewer " + suffix,
        "email": f"acceptance-zip-reviewer-{suffix}@example.test",
        "password": secrets.token_urlsafe(24)})
    outsider = Client()
    outsider_identity = outsider.call("POST", "/auth/signup", {
        "name": "Acceptance ZIP outsider " + suffix,
        "email": f"acceptance-zip-outsider-{suffix}@example.test",
        "password": secrets.token_urlsafe(24)})
    assert viewer_identity["role"] == outsider_identity["role"] == "viewer"
    viewer.call("GET", f"/datasets/{dataset['id']}", expected=403)
    zip_call(viewer, "/imports/zip/validate", payload, expected=403)
    zip_call(viewer, f"/datasets/{dataset['id']}/import-zip", payload, expected=403)

    presets = admin.call("GET", "/presets")["items"]
    replay = next((item for item in presets if item["backend"] == "saved_replay"), None)
    if not replay:
        raise AssertionError("Local acceptance requires an existing saved_replay preset")
    team = admin.call("POST", "/teams", {"name": "Acceptance ZIP team " + suffix})
    admin.call("POST", f"/teams/{team['id']}/members", {"user_id": viewer_identity["id"]})
    batch = admin.call("POST", "/batches", {
        "name": "Acceptance ZIP batch " + suffix,
        "dataset_id": dataset["id"],
        "mode": "appendable",
        "preset_id": replay["id"],
        "task_ids": [task_id],
        "team_ids": [team["id"]],
    })
    batch_id = batch["id"]
    batch_path = f"/batches/{batch_id}/tasks/{task_id}"
    outsider.call("GET", batch_path, expected=403)
    first_member = viewer.call("GET", batch_path)
    first_member_id = first_member["member"]["id"]
    first_url = first_member["task"]["steps"][0]["screenshot_url"]
    first_bytes = viewer.call("GET", first_url.removeprefix("/api"))
    assert first_bytes == original_image
    outsider.call("GET", first_url.removeprefix("/api"), expected=403)

    changed = zip_call(admin, f"/datasets/{dataset['id']}/import-zip",
                       archive_bytes([acceptance_task(task_id, image_path)], revised_image))
    assert changed["created"] == 0 and changed["revised"] == 1 and changed["unchanged"] == 0, \
        "Changed screenshot checksum did not create a task revision"
    current_task = admin.call("GET", f"/datasets/{dataset['id']}")["tasks"][0]
    current_dataset_url = current_task["steps"][0]["screenshot_url"]
    assert current_task["revision_id"] != initial_task["revision_id"]
    assert "revision_id=" + current_task["revision_id"] in current_dataset_url
    assert admin.call("GET", current_dataset_url.removeprefix("/api")) == revised_image
    assert admin.call("GET", initial_dataset_url.removeprefix("/api")) == original_image
    synced = admin.call("POST", f"/batches/{batch_id}/sync", {})
    assert synced["added"] == 1
    members = admin.call("GET", f"/batches/{batch_id}/tasks")["items"]
    matching = [member for member in members if member["task_id"] == task_id]
    assert len(matching) == 2 and len({member["revision_id"] for member in matching}) == 2
    newest = max(matching, key=lambda member: member["revision"])
    latest = viewer.call("GET", f"{batch_path}?member_id={newest['member_id']}")
    assert latest["member"]["id"] == newest["member_id"]
    latest_url = latest["task"]["steps"][0]["screenshot_url"]
    assert "member_id=" + newest["member_id"] in latest_url
    latest_bytes = viewer.call("GET", latest_url.removeprefix("/api"))
    assert latest_bytes == revised_image
    outsider.call("GET", latest_url.removeprefix("/api"), expected=403)
    pass_check("Batch sync carries the changed image revision into member-scoped screenshot access")

    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_url": BASE,
        "provider_calls": 0,
        "checks": [
            "ZIP preview without persistence",
            "Valid import and repeat idempotency",
            "Invalid archive atomicity",
            "Dataset/batch/artifact authorization and viewer ZIP import rejection",
            "Dataset screenshot URLs remain pinned to their immutable revision",
            "Changed image checksum creates a revision and syncs as member-scoped evidence",
        ],
        "dataset_id": dataset["id"],
        "batch_id": batch_id,
        "task_id": task_id,
        "revision_ids": [member["revision_id"] for member in matching],
        "note": "Named acceptance fixtures only. No batch jobs are started; no model/provider calls are made.",
    }
    output = ROOT / "platform/evidence/zip-import-verification.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Saved platform/evidence/zip-import-verification.json")


if __name__ == "__main__":
    main()
