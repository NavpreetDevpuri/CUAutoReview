from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from conftest import isolate
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app import main
from app.models import StoredArtifact, TaskDefinition, TaskRevision

ORIGIN = {"Origin": "http://testserver"}


def png_bytes(color):
    stream = BytesIO()
    Image.new("RGB", (2, 2), color).save(stream, format="PNG")
    return stream.getvalue()


PNG = png_bytes((20, 40, 60))


@pytest.fixture
def zip_clients(tmp_path, monkeypatch):
    engine, factory = isolate(tmp_path, monkeypatch)
    with TestClient(main.app) as admin:
        response = admin.post(
            "/api/auth/signup",
            json={"name": "ZIP Admin", "email": "zip-admin@example.test", "password": "test-password-123"},
        )
        assert response.status_code == 200, response.text
        yield {"admin": admin, "factory": factory, "engine": engine}
    engine.dispose()


def manifest_task(task_id="zip-task", outcome="passed", screenshot="assets/shot.png"):
    step = {"step_id": "step-1", "action": "click", "observation": "Button displayed", "evidence_refs": ["event-1"]}
    if screenshot is not None:
        step["screenshot"] = screenshot
    return {
        "task_id": task_id,
        "title": "ZIP fixture task",
        "instruction": "Click the visible button",
        "outcome": outcome,
        "score": 1 if outcome == "passed" else 0,
        "source": {"dataset": "fixture"},
        "steps": [step],
    }


def archive_bytes(tasks=None, *, manifest="dataset.json", members=None):
    content = {"format": "cuautoreview", "tasks": tasks if tasks is not None else [manifest_task()]}
    members = members or {"assets/shot.png": PNG}
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr(manifest, json.dumps(content))
        for path, value in members.items():
            archive.writestr(path, value)
    return stream.getvalue()


def zip_post(client, path, payload, *, content_type="application/zip"):
    return client.post(path, content=payload, headers={**ORIGIN, "Content-Type": content_type})


def test_validate_and_import_zip_persists_scoped_artifact_and_revision_hashes_assets(zip_clients):
    admin = zip_clients["admin"]
    payload = archive_bytes()
    before = admin.post("/api/datasets", json={"name": "ZIP fixture"}, headers=ORIGIN).json()
    preview = zip_post(admin, "/api/imports/zip/validate", payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["valid"] is True
    assert preview.json()["task_count"] == 1 and preview.json()["screenshot_count"] == 1
    assert preview.json()["tasks"][0] == {
        "task_id": "zip-task",
        "title": "ZIP fixture task",
        "step_count": 1,
        "outcome": "passed",
    }
    with zip_clients["factory"]() as db:
        assert db.scalar(select(func.count(TaskDefinition.id))) == 0

    imported = zip_post(admin, f"/api/datasets/{before['id']}/import-zip", payload)
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1 and imported.json()["warnings"] == []
    repeated = zip_post(admin, f"/api/datasets/{before['id']}/import-zip", payload)
    assert repeated.status_code == 200 and repeated.json()["unchanged"] == 1
    task = admin.get(f"/api/datasets/{before['id']}").json()["tasks"][0]
    assert task["steps"][0]["artifact_status"] == "recorded"
    old_url = task["steps"][0]["screenshot_url"]
    assert f"revision_id={task['revision_id']}" in old_url
    assert admin.get(old_url).content == PNG
    with zip_clients["factory"]() as db:
        artifact = db.scalar(select(StoredArtifact).where(StoredArtifact.task_revision_id == task["revision_id"]))
        assert artifact and artifact.object_key and artifact.sha256

    changed_payload = archive_bytes(members={"assets/shot.png": png_bytes((60, 40, 20))})
    changed = zip_post(admin, f"/api/datasets/{before['id']}/import-zip", changed_payload)
    assert changed.status_code == 200 and changed.json()["revised"] == 1
    current = admin.get(f"/api/datasets/{before['id']}").json()["tasks"][0]
    current_url = current["steps"][0]["screenshot_url"]
    assert current["revision_id"] != task["revision_id"]
    assert f"revision_id={current['revision_id']}" in current_url
    assert admin.get(current_url).content == png_bytes((60, 40, 20))
    assert admin.get(old_url).content == PNG
    with zip_clients["factory"]() as db:
        assert db.scalar(select(func.count(TaskRevision.id))) == 2


def test_zip_artifacts_are_copied_to_batch_members_and_revocation_is_immediate(zip_clients):
    admin = zip_clients["admin"]
    dataset = admin.post("/api/datasets", json={"name": "ZIP batch fixture"}, headers=ORIGIN).json()
    imported = zip_post(admin, f"/api/datasets/{dataset['id']}/import-zip", archive_bytes())
    assert imported.status_code == 200, imported.text
    preset = admin.post(
        "/api/presets",
        headers=ORIGIN,
        json={"name": "Saved fixture", "backend": "saved_replay", "reasoning": "none", "budget_usd": 0},
    ).json()
    team = admin.post("/api/teams", headers=ORIGIN, json={"name": "ZIP reviewers"}).json()
    viewer = TestClient(main.app)
    created = viewer.post(
        "/api/auth/signup",
        headers=ORIGIN,
        json={"name": "ZIP Viewer", "email": "zip-viewer@example.test", "password": "viewer-password"},
    ).json()
    forbidden_preview = zip_post(viewer, "/api/imports/zip/validate", archive_bytes())
    forbidden_import = zip_post(viewer, f"/api/datasets/{dataset['id']}/import-zip", archive_bytes())
    assert forbidden_preview.status_code == forbidden_import.status_code == 403
    assert (
        admin.post(f"/api/teams/{team['id']}/members", headers=ORIGIN, json={"user_id": created["id"]}).status_code
        == 200
    )
    batch = admin.post(
        "/api/batches",
        headers=ORIGIN,
        json={
            "dataset_id": dataset["id"],
            "name": "ZIP batch",
            "mode": "fixed",
            "preset_id": preset["id"],
            "task_ids": ["zip-task"],
            "team_ids": [team["id"]],
        },
    ).json()
    detail = viewer.get(f"/api/batches/{batch['id']}/tasks/zip-task")
    assert detail.status_code == 200, detail.text
    step = detail.json()["task"]["steps"][0]
    assert step["artifact_status"] == "recorded"
    response = viewer.get(step["screenshot_url"])
    assert response.status_code == 200 and response.content == PNG
    with zip_clients["factory"]() as db:
        member_id = detail.json()["member"]["id"]
        member_artifact = db.scalar(select(StoredArtifact).where(StoredArtifact.member_id == member_id))
        assert member_artifact and member_artifact.object_key
    assert admin.delete(f"/api/teams/{team['id']}/members/{created['id']}", headers=ORIGIN).status_code == 204
    assert viewer.get(step["screenshot_url"]).status_code == 403


def test_zip_validation_reports_warnings_for_unknown_outcomes_and_unused_files(zip_clients):
    payload = archive_bytes(
        tasks=[manifest_task("unknown-task", "unknown", screenshot=None)],
        members={"README.md": b"Harmless documentation", "assets/unused.png": PNG},
    )
    response = zip_post(zip_clients["admin"], "/api/imports/zip/validate", payload)
    assert response.status_code == 200, response.text
    codes = {item["code"] for item in response.json()["warnings"]}
    assert {"unknown_outcome", "screenshots_absent", "unused_screenshot", "unused_file"} <= codes


@pytest.mark.parametrize(
    "payload,code",
    [
        (archive_bytes(members={"../escape.png": PNG}), "unsafe_path"),
        (archive_bytes(tasks=[manifest_task(screenshot="assets/missing.png")], members={}), "missing_screenshot_asset"),
        (archive_bytes(tasks=[manifest_task("duplicate"), manifest_task("duplicate")]), "duplicate_task_id"),
        (
            archive_bytes(
                tasks=[
                    {
                        **manifest_task(),
                        "steps": [
                            {"step_id": "same", "action": "a", "observation": "a"},
                            {"step_id": "same", "action": "b", "observation": "b"},
                        ],
                    }
                ]
            ),
            "duplicate_step_id",
        ),
        (
            archive_bytes(
                tasks=[
                    {
                        **manifest_task(),
                        "steps": [
                            {"step_id": " same ", "action": "a", "observation": "a"},
                            {"step_id": "same", "action": "b", "observation": "b"},
                        ],
                    }
                ]
            ),
            "duplicate_step_id",
        ),
        (archive_bytes(members={"assets/bad.svg": b"<svg></svg>"}), "unsupported_attachment"),
    ],
)
def test_invalid_zip_import_is_structured_and_atomic(zip_clients, payload, code):
    admin = zip_clients["admin"]
    dataset = admin.post("/api/datasets", headers=ORIGIN, json={"name": f"Invalid {code}"}).json()
    result = zip_post(admin, f"/api/datasets/{dataset['id']}/import-zip", payload)
    assert result.status_code == 422
    detail = result.json()["detail"]
    assert detail["message"] == "ZIP dataset is invalid"
    assert any(issue["code"] == code for issue in detail["errors"])
    with zip_clients["factory"]() as db:
        assert db.scalar(select(func.count(TaskDefinition.id))) == 0


def test_zip_rejects_symlinks_and_non_zip_content_type(zip_clients):
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        info = ZipInfo("assets/link.png")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "target.png")
        archive.writestr(
            "dataset.json", json.dumps({"format": "cuautoreview", "tasks": [manifest_task(screenshot=None)]})
        )
    symlink = zip_post(zip_clients["admin"], "/api/imports/zip/validate", stream.getvalue())
    assert symlink.status_code == 422
    assert any(item["code"] == "unsafe_file_type" for item in symlink.json()["detail"]["errors"])

    wrong_type = zip_post(
        zip_clients["admin"], "/api/imports/zip/validate", archive_bytes(), content_type="application/json"
    )
    assert wrong_type.status_code == 422
    assert wrong_type.json()["detail"]["errors"][0]["code"] == "unsupported_media_type"


def test_zip_rejects_truncated_image_with_valid_signature(zip_clients):
    response = zip_post(
        zip_clients["admin"], "/api/imports/zip/validate", archive_bytes(members={"assets/shot.png": PNG[:12]})
    )
    assert response.status_code == 422
    assert any(item["code"] == "invalid_image_content" for item in response.json()["detail"]["errors"])


def test_zip_rejects_duplicate_json_object_keys(zip_clients):
    duplicate_keys = (
        b'{"format":"cuautoreview","format":"cuautoreview","tasks":['
        b'{"task_id":"duplicate-json-key","title":"Task","instruction":"Do work","steps":[]}]}'
    )
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("dataset.json", duplicate_keys)
    response = zip_post(zip_clients["admin"], "/api/imports/zip/validate", stream.getvalue())
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["code"] == "invalid_manifest"


def test_zip_caps_diagnostics_and_rejects_pathological_manifest_nesting(zip_clients):
    admin = zip_clients["admin"]
    bad_tasks = [{"task_id": f"bad-{i}", "title": "", "instruction": "", "steps": []} for i in range(300)]
    too_many_errors = zip_post(admin, "/api/imports/zip/validate", archive_bytes(tasks=bad_tasks))
    assert too_many_errors.status_code == 422
    assert len(too_many_errors.json()["detail"]["errors"]) <= 100
    assert too_many_errors.json()["detail"]["errors"][-1]["code"] == "diagnostics_truncated"

    nested = "[" * 2000 + "0" + "]" * 2000
    yaml_payload = (
        b"format: cuautoreview\ntasks:\n  - task_id: x\n    title: x\n    instruction: x\n    steps: " + nested.encode()
    )
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("dataset.yaml", yaml_payload)
    response = zip_post(admin, "/api/imports/zip/validate", stream.getvalue())
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["code"] in {"invalid_manifest", "invalid_schema"}

    deep_json = b'{"format":"cuautoreview","tasks":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}"
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("dataset.json", deep_json)
    response = zip_post(admin, "/api/imports/zip/validate", stream.getvalue())
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["code"] == "invalid_manifest"

    alias_yaml = b"format: cuautoreview\ntasks: &tasks []\nextra: *tasks\n"
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("dataset.yaml", alias_yaml)
    response = zip_post(admin, "/api/imports/zip/validate", stream.getvalue())
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["code"] == "invalid_manifest"


def test_zip_caps_warning_diagnostics(zip_clients):
    tasks = [manifest_task(f"warning-{i}", "unknown", screenshot=None) for i in range(100)]
    response = zip_post(zip_clients["admin"], "/api/imports/zip/validate", archive_bytes(tasks=tasks))
    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert len(warnings) == 100
    assert warnings[-1]["code"] == "diagnostics_truncated"
