from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import main
from app.database import make_engine, make_session_factory, session_dependency
from app.models import Batch, BatchMember, Job, JobAttempt, OutboxEvent, ReviewResult, TaskRevision, TaxonomyRelease, User, utcnow


ORIGIN = {"Origin": "http://testserver"}
PNG_BYTES = b"\x89PNG\r\n\x1a\nrecorded screenshot"


@asynccontextmanager
async def no_lifespan(_app):
    yield


@pytest.fixture
def app_clients(tmp_path, monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    main.init_db(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "settings", replace(main.settings, seed_poc=False,
                                                    object_store_backend="local",
                                                    local_artifact_dir=tmp_path / "artifacts"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    dependency = main.get_db
    main.app.dependency_overrides[dependency] = session_dependency(factory)
    # Skip the production lifespan (database init, S3 bucket check, outbox loop) in tests.
    monkeypatch.setattr(main.app.router, "lifespan_context", no_lifespan)
    with TestClient(main.app) as admin:
        response = admin.post("/api/auth/signup", json={"name": "Admin", "email": "admin@example.test",
                                  "password": "test-password-123"})
        assert response.status_code == 200, response.text
        yield {"admin": admin, "factory": factory, "engine": engine, "tmp_path": tmp_path}
    main.app.dependency_overrides.pop(dependency, None)
    engine.dispose()


def post(client, path, **kwargs):
    return client.post(path, headers=ORIGIN, **kwargs)


def signup_viewer(client):
    response = post(client, "/api/auth/signup", json={"name": "Viewer", "email": "viewer@example.test",
                                                     "password": "viewer-password"})
    assert response.status_code == 200, response.text
    return response.json()


def task(task_id="task-1", outcome="failed", screenshot=None):
    step = {"step_id": "1", "intent": None, "action": "click", "observation": "Button displayed",
            "evidence_refs": ["event_1", "frame_1"]}
    if screenshot:
        step["screenshot"] = screenshot
    return {"task_id": task_id, "title": f"Task {task_id}", "instruction": "Complete a local task",
            "outcome": outcome, "score": 0 if outcome == "failed" else 1,
            "source": {"dataset": "fixture"}, "steps": [step]}


def create_dataset(client, name="Fixture dataset"):
    response = post(client, "/api/datasets", json={"name": name, "description": "fixture"})
    assert response.status_code == 200, response.text
    return response.json()


def import_tasks(client, dataset_id, *tasks):
    return post(client, f"/api/datasets/{dataset_id}/import",
                json={"format": "cuautoreview", "tasks": list(tasks)})


def create_saved_preset(client):
    response = post(client, "/api/presets", json={"name": "Saved fixture", "backend": "saved_replay",
        "model": None, "reasoning": "none", "budget_usd": 0, "configuration": {}})
    assert response.status_code == 200, response.text
    return response.json()


def create_batch(client, dataset, preset, **overrides):
    body = {"dataset_id": dataset["id"], "name": "Fixture batch", "mode": "appendable",
            "preset_id": preset["id"], **overrides}
    response = post(client, "/api/batches", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_execution_snapshot_defaults_and_bounds_image_delivery_at_32():
    workflow = main.workflow_catalog()[0]
    base = {"backend": "saved_replay", "model": None, "budget_usd": 0, "configuration": {}}
    defaulted = main.execution_snapshot(base, workflow)
    assert defaulted["configuration"]["max_images"] == 32
    explicitly_bounded = main.execution_snapshot({**base,
        "configuration": {"max_images": 32}}, workflow)
    assert explicitly_bounded["configuration"]["max_images"] == 32
    with pytest.raises(main.HTTPException):
        main.execution_snapshot({**base, "configuration": {"max_images": 33}}, workflow)


def test_first_signup_and_workspace_role_enforcement(app_clients):
    admin = app_clients["admin"]
    viewer = TestClient(main.app)
    data = signup_viewer(viewer)
    assert data["role"] == "viewer"
    assert admin.get("/api/auth/me").json()["role"] == "admin"
    denied = post(viewer, "/api/datasets", json={"name": "Denied"})
    assert denied.status_code == 403


def test_provider_model_catalog_sync_is_admin_only_and_returns_safe_snapshot(app_clients):
    admin = app_clients["admin"]
    anonymous = TestClient(main.app)
    snapshot = {"backend": "gemini_cli", "status": "available", "source": "google_models_api",
        "fetched_at": "2026-09-27T09:00:00Z", "models": [{"id": "gemini-3.8-flash",
        "display_name": "Gemini 3.8 Flash", "provider": "google", "recommended": True}]}
    assert anonymous.get("/api/providers/models", params={"backend": "gemini_cli"}).status_code == 401
    empty_catalog = admin.get("/api/providers/models", params={"backend": "gemini_cli"})
    assert empty_catalog.status_code == 200
    assert empty_catalog.json()["status"] == "unknown" and empty_catalog.json()["models"] == []
    assert admin.get("/api/providers/models", params={"backend": "codex"}).json()["status"] == "unknown"

    synced = post(admin, "/api/providers/models/sync", json=snapshot)
    assert synced.status_code == 200, synced.text
    assert synced.json()["backend"] == "gemini_cli"
    assert synced.json()["models"][0]["id"] == "gemini-3.8-flash"
    assert synced.json()["status"] == "available"
    assert synced.json()["source"] == "google_models_api"
    assert "api_key" not in synced.text.lower()
    persisted = admin.get("/api/providers/models", params={"backend": "gemini_cli"})
    assert persisted.json()["status"] == "available"
    assert persisted.json()["models"][0]["id"] == "gemini-3.8-flash"

    viewer = TestClient(main.app)
    signup_viewer(viewer)
    denied = post(viewer, "/api/providers/models/sync", json=snapshot)
    assert denied.status_code == 403

    invalid = {**snapshot, "models": [{"id": "gemini/gemini-3.8-flash", "provider": "google"}]}
    rejected = post(admin, "/api/providers/models/sync", json=invalid)
    assert rejected.status_code == 422
    assert admin.get("/api/providers/models", params={"backend": "gemini_cli"}).json()["models"][0]["id"] == "gemini-3.8-flash"


def test_task_history_includes_run_created_at(app_clients):
    client = app_clients["admin"]
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task()).status_code == 200
    preset = create_saved_preset(client)
    run = create_batch(client, dataset, preset, task_ids=["task-1"])
    task_definition_id = client.get(f"/api/datasets/{dataset['id']}").json()["tasks"][0]["task_definition_id"]
    history = client.get(f"/api/datasets/{dataset['id']}/tasks/{task_definition_id}")
    assert history.status_code == 200, history.text
    assert history.json()["runs"][0]["run_id"] == run["id"]
    assert history.json()["runs"][0]["created_at"] == run["created_at"]


def test_appendable_sync_is_idempotent_and_fixed_batches_stay_frozen(app_clients):
    client = app_clients["admin"]
    dataset = create_dataset(client)
    imported = import_tasks(client, dataset["id"], task())
    assert imported.status_code == 200, imported.text
    preset = create_saved_preset(client)
    appendable = create_batch(client, dataset, preset, task_ids=["task-1"])

    first = post(client, f"/api/batches/{appendable['id']}/sync")
    second = post(client, f"/api/batches/{appendable['id']}/sync")
    assert first.status_code == second.status_code == 200
    assert first.json()["wave"]["id"] == second.json()["wave"]["id"]
    assert first.json()["idempotent_replay"] is False
    assert second.json()["idempotent_replay"] is True

    fixed = post(client, "/api/batches", json={"dataset_id": dataset["id"], "name": "Fixed batch",
        "mode": "fixed", "preset_id": preset["id"], "task_ids": ["task-1"]}).json()
    changed = import_tasks(client, dataset["id"], task("task-1", "passed"), task("task-2", "failed"))
    assert changed.status_code == 200, changed.text
    synced = post(client, f"/api/batches/{appendable['id']}/sync")
    assert synced.status_code == 200 and synced.json()["added"] == 2
    repeated = post(client, f"/api/batches/{appendable['id']}/sync")
    assert repeated.status_code == 200 and repeated.json()["idempotent_replay"] is True
    fixed_sync = post(client, f"/api/batches/{fixed['id']}/sync")
    assert fixed_sync.status_code == 409
    members = client.get(f"/api/batches/{fixed['id']}/tasks").json()["items"]
    assert len(members) == 1 and members[0]["revision"] == 1


def test_team_batch_access_is_revoked_server_side_and_artifacts_are_recorded(app_clients):
    client = app_clients["admin"]
    tmp = app_clients["tmp_path"]
    screenshot = "data/source/fixture/shot.png"
    file_path = tmp / "poc" / screenshot
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(PNG_BYTES)
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task(screenshot=screenshot)).status_code == 200
    preset = create_saved_preset(client)
    team = post(client, "/api/teams", json={"name": "Reviewers"}).json()

    viewer = TestClient(main.app)
    user = signup_viewer(viewer)
    assert post(client, f"/api/teams/{team['id']}/members", json={"user_id": user["id"]}).status_code == 200
    batch = create_batch(client, dataset, preset, team_ids=[team["id"]])
    detail = viewer.get(f"/api/batches/{batch['id']}/tasks/task-1")
    assert detail.status_code == 200
    step = detail.json()["task"]["steps"][0]
    assert step["artifact_status"] == "recorded"
    assert viewer.get(step["screenshot_url"]).content == PNG_BYTES
    assert client.get(step["screenshot_url"]).status_code == 200

    hidden_batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    assert post(client, f"/api/batches/{batch['id']}/start", json={}).status_code == 200
    assert post(client, f"/api/batches/{hidden_batch['id']}/start", json={}).status_code == 200
    admin_overview = client.get("/api/overview").json()
    viewer_overview = viewer.get("/api/overview").json()
    assert admin_overview["counts"]["batches"] == 2 and admin_overview["counts"]["tasks"] == 2
    assert viewer_overview["counts"]["batches"] == 1 and viewer_overview["counts"]["tasks"] == 1
    assert viewer_overview["jobs"]["queued"] == 1
    assert len(viewer.get("/api/jobs").json()["items"]) == 1
    assert len(viewer_overview["recent_batches"]) == 1
    assert all(event["actor_id"] == user["id"] for event in viewer_overview["activity"])
    feedback = viewer.post(f"/api/batches/{batch['id']}/tasks/task-1/feedback", headers=ORIGIN,
                           json={"text": "Reviewer scoped activity event"})
    assert feedback.status_code == 200, feedback.text
    scoped_activity = viewer.get("/api/activity").json()
    assert scoped_activity["items"] and all(event["actor_id"] == user["id"] for event in scoped_activity["items"])
    assert client.get("/api/overview").json()["counts"]["batches"] == 2

    assert client.delete(f"/api/teams/{team['id']}/members/{user['id']}", headers=ORIGIN).status_code == 204
    assert viewer.get(f"/api/batches/{batch['id']}/tasks/task-1").status_code == 403
    assert viewer.get(step["screenshot_url"]).status_code == 403
    assert viewer.get(f"/api/artifacts/task-1/not-recorded.png").status_code == 404


def test_taxonomy_candidate_stales_after_feedback_and_publishes_exact_hash(app_clients):
    client = app_clients["admin"]
    proposal = post(client, "/api/taxonomy/proposals", json={"name": "Wrong target",
        "description": "A visible action reaches a different control.", "kind": "new_label",
        "evidence_refs": ["event_1"]})
    assert proposal.status_code == 200, proposal.text
    candidate = post(client, "/api/taxonomy/consolidate", json={})
    assert candidate.status_code == 200, candidate.text
    feedback = post(client, f"/api/taxonomy/proposals/{proposal.json()['id']}/feedback",
                    json={"text": "Keep the definition concrete."})
    assert feedback.status_code == 200
    stale = post(client, f"/api/taxonomy/candidates/{candidate.json()['id']}/approve",
                 json={"expected_hash": candidate.json()["hash"], "version": candidate.json()["version"]})
    assert stale.status_code == 409

    fresh = post(client, "/api/taxonomy/consolidate", json={}).json()
    approved = post(client, f"/api/taxonomy/candidates/{fresh['id']}/approve",
                    json={"expected_hash": fresh["hash"], "version": fresh["version"]})
    assert approved.status_code == 200, approved.text
    assert approved.json()["labels"][0]["status"] == "active"
    assert client.get("/api/taxonomy").json()["releases"]


def test_rejected_candidate_cannot_be_published(app_clients):
    client = app_clients["admin"]
    post(client, "/api/taxonomy/proposals", json={"name": "Draft", "description": "Draft definition",
        "kind": "new_label"})
    candidate = post(client, "/api/taxonomy/consolidate", json={}).json()
    rejected = post(client, f"/api/taxonomy/candidates/{candidate['id']}/reject", json={"reason": "Not specific."})
    assert rejected.status_code == 200
    assert client.get("/api/taxonomy").json()["candidates"][0]["status"] == "rejected"
    approved = post(client, f"/api/taxonomy/candidates/{candidate['id']}/approve",
                    json={"expected_hash": candidate["hash"], "version": candidate["version"]})
    assert approved.status_code == 409


def test_optional_taxonomy_curation_requires_budget_and_discards_stale_drafts(app_clients, monkeypatch):
    from app import taxonomy_backend

    client = app_clients["admin"]
    proposal = post(client, "/api/taxonomy/proposals", json={"name": "Curated label",
        "description": "A concrete observable mechanism.", "kind": "label"}).json()
    preset = post(client, "/api/presets", json={"name": "Curation fixture", "backend": "litellm",
        "model": "openai/gpt-test", "reasoning": "low", "budget_usd": 0.25,
        "configuration": {}}).json()
    preset_revision_id = preset["revisions"][0]["id"]
    calls = []

    def fake_curation(*, preset_revision, base_content, proposals):
        calls.append((preset_revision, proposals))
        label_id = proposals[0]["proposal_id"]
        return {"content": {"labels": [{"id": label_id, "name": "Curated label",
                "description": "A concrete observable mechanism.", "status": "active"}],
                "mappings": [{"proposal_id": label_id, "canonical_label_id": label_id,
                              "rationale": "The candidate preserves the exact proposal."}],
                "unresolved": [], "draft_proposals": proposals},
                "usage": {"kind": "provider_reported_tokens", "estimated_usd": 0.01},
                "provenance": {"backend": "model_api", "human_approval_required": True}}

    monkeypatch.setattr(taxonomy_backend, "consolidate_drafts", fake_curation)
    monkeypatch.setenv("ALLOW_HOSTED_INFERENCE", "true")
    unconfirmed = post(client, "/api/taxonomy/consolidate", json={"preset_revision_id": preset_revision_id})
    assert unconfirmed.status_code == 409 and calls == []

    confirmed = post(client, "/api/taxonomy/consolidate", json={"preset_revision_id": preset_revision_id,
        "confirm_budget": True, "expected_budget_usd": 0.25})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["curation"]["usage"]["estimated_usd"] == 0.01
    assert calls and calls[-1][1][0]["proposal_id"] == proposal["id"]

    def mutate_head_during_request(**kwargs):
        monkeypatch.setattr(main, "_taxonomy_proposal_snapshot",
            lambda *_args, **_kwargs: ({"changed-head": "0" * 64}, kwargs["proposals"]))
        return fake_curation(**kwargs)

    monkeypatch.setattr(taxonomy_backend, "consolidate_drafts", mutate_head_during_request)
    stale = post(client, "/api/taxonomy/consolidate", json={"preset_revision_id": preset_revision_id,
        "confirm_budget": True, "expected_budget_usd": 0.25})
    assert stale.status_code == 409
    assert client.get("/api/taxonomy").json()["candidates"][-1]["id"] == confirmed.json()["id"]


def test_hosted_retry_rechecks_explicit_budget_confirmation(app_clients, monkeypatch):
    from app import review_backends

    client = app_clients["admin"]
    monkeypatch.setenv("ALLOW_HOSTED_INFERENCE", "true")
    monkeypatch.setattr(review_backends, "provider_capabilities", lambda: [
        {"id": "model_api", "configured": True, "execution_enabled": True}])
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task()).status_code == 200
    preset = post(client, "/api/presets", json={"name": "Retry confirmation", "backend": "litellm",
        "model": "openai/gpt-test", "budget_usd": 0.25}).json()
    batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    planned = client.get(f"/api/batches/{batch['id']}").json()["progress"]
    assert planned["default_max_attempts"] == 4
    assert planned["planned_allowance_usd"] == pytest.approx(1.0)

    denied = post(client, f"/api/batches/{batch['id']}/start", json={})
    assert denied.status_code == 409
    started = post(client, f"/api/batches/{batch['id']}/start", json={"confirm_budget": True,
        "expected_budget_usd": 0.25})
    assert started.status_code == 200 and started.json()["jobs_added"] == 1
    with app_clients["factory"]() as db:
        job = db.scalar(select(Job))
        job.status = "failed"
        job.attempt_count = 1
        db.add(JobAttempt(job_id=job.id, attempt_number=1, generation=job.generation,
            fence_token=job.fence_token, status="failed",
            usage={"kind": "unknown", "estimated_usd": None}, cost_usd=None))
        job_id = job.id
        db.commit()

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    assert detail.json()["backend"] == "litellm"
    assert detail.json()["model"] == "openai/gpt-test"
    assert detail.json()["cumulative_cost_usd"] is None
    assert detail.json()["unknown_cost_attempts"] == 1

    unconfirmed = post(client, f"/api/jobs/{job_id}/retry", json={})
    wrong_budget = post(client, f"/api/jobs/{job_id}/retry", json={"confirm_budget": True,
        "expected_budget_usd": 0.20})
    assert unconfirmed.status_code == wrong_budget.status_code == 409
    retried = post(client, f"/api/jobs/{job_id}/retry", json={"confirm_budget": True,
        "expected_budget_usd": 0.25})
    assert retried.status_code == 200 and retried.json()["generation"] == 2


def test_duplicate_worker_delivery_commits_one_review_revision(app_clients, monkeypatch):
    from app import queue, review_backends

    client = app_clients["admin"]
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task(outcome="passed")).status_code == 200
    preset = create_saved_preset(client)
    batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    started = post(client, f"/api/batches/{batch['id']}/start", json={})
    assert started.status_code == 200
    with app_clients["factory"]() as db:
        job = db.scalar(select(Job))
        assert job and job.status == "queued"
        job_id, generation = job.id, job.generation

    monkeypatch.setattr(queue, "SessionLocal", app_clients["factory"])
    monkeypatch.setattr(queue, "settings", replace(queue.settings, object_store_backend="local",
        local_artifact_dir=app_clients["tmp_path"] / "worker-artifacts"))
    monkeypatch.setattr(review_backends, "execute_review", lambda **_kwargs: {
        "review": {"review_kind": "pass_recovery", "steps": [], "episodes": []},
        "usage": {"kind": "saved_replay", "estimated_usd": 0, "billed": False},
        "provenance": {"new_inference": False}, "proposals": []})
    first = queue.run_review.run(job_id, generation)
    duplicate = queue.run_review.run(job_id, generation)
    assert first["status"] == "completed"
    assert duplicate["status"] == "obsolete_or_not_claimable"
    with app_clients["factory"]() as db:
        assert db.scalar(select(func.count(ReviewResult.id))) == 1
        job = db.get(Job, job_id)
        assert job.status == "completed" and job.cost_usd == 0


def test_resume_rearms_sent_outbox_and_repeated_start_preserves_queued_work(app_clients):
    client = app_clients["admin"]
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task(outcome="passed")).status_code == 200
    preset = create_saved_preset(client)
    batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    started = post(client, f"/api/batches/{batch['id']}/start", json={})
    assert started.status_code == 200 and started.json()["status"] == "running"
    with app_clients["factory"]() as db:
        job = db.scalar(select(Job))
        job_id = job.id
        generation = job.generation
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job.id))
        event.status = "sent"  # Simulate delivery acknowledged after the worker saw a pause.
        db.commit()
    assert post(client, f"/api/batches/{batch['id']}/pause").status_code == 200
    resumed = post(client, f"/api/batches/{batch['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "running"
    with app_clients["factory"]() as db:
        event = db.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job_id,
            OutboxEvent.generation == generation))
        assert event.status == "pending" and event.relay_owner is None
    repeated = post(client, f"/api/batches/{batch['id']}/start", json={})
    assert repeated.status_code == 200 and repeated.json()["jobs_added"] == 0
    assert repeated.json()["status"] == "running"


def test_cancelled_batches_cannot_restart_and_unknown_outcomes_wait_for_review(app_clients):
    client = app_clients["admin"]
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task(outcome="passed")).status_code == 200
    preset = create_saved_preset(client)
    batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    assert post(client, f"/api/batches/{batch['id']}/start", json={}).status_code == 200
    assert post(client, f"/api/batches/{batch['id']}/cancel").json()["status"] == "cancelled"
    assert post(client, f"/api/batches/{batch['id']}/start", json={}).status_code == 409
    assert post(client, f"/api/batches/{batch['id']}/resume").status_code == 409

    unknown_dataset = create_dataset(client, "Unknown outcome dataset")
    assert import_tasks(client, unknown_dataset["id"], task("task-unknown", outcome="unknown")).status_code == 200
    waiting_batch = create_batch(client, unknown_dataset, preset, task_ids=["task-unknown"])
    started = post(client, f"/api/batches/{waiting_batch['id']}/start", json={})
    assert started.status_code == 200 and started.json()["jobs_added"] == 0
    assert started.json()["status"] == "awaiting_review"


def test_worker_refreshes_latest_drafts_over_batch_pinned_taxonomy(app_clients, monkeypatch):
    from app import queue, review_backends

    client = app_clients["admin"]
    user = client.get("/api/auth/me").json()
    pinned_content = {"labels": [{"id": "pinned-label", "name": "Pinned", "description": "Pinned definition",
                                    "status": "active"}]}
    with app_clients["factory"]() as db:
        pinned = TaxonomyRelease(workspace_id=user["workspace_id"], version="1.0.0", content=pinned_content,
            content_hash=main.digest(pinned_content), created_by=user["id"])
        db.add(pinned)
        db.commit()
        pinned_id = pinned.id

    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task(outcome="passed")).status_code == 200
    preset = create_saved_preset(client)
    batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    assert batch["taxonomy_release_id"] == pinned_id

    latest_content = {"labels": pinned_content["labels"] + [{"id": "latest-only", "name": "Unpinned",
        "description": "Must not be substituted", "status": "active"}]}
    with app_clients["factory"]() as db:
        newer = TaxonomyRelease(workspace_id=user["workspace_id"], version="2.0.0", content=latest_content,
            content_hash=main.digest(latest_content), created_by=user["id"], created_at=utcnow() + timedelta(seconds=1))
        db.add(newer)
        db.commit()

    proposal = post(client, "/api/taxonomy/proposals", json={"name": "Initial draft",
        "description": "Original definition", "kind": "label"}).json()
    started = post(client, f"/api/batches/{batch['id']}/start", json={})
    assert started.status_code == 200 and started.json()["jobs_added"] == 1
    edited = client.patch(f"/api/taxonomy/proposals/{proposal['id']}", headers=ORIGIN,
        json={"name": "Fresh draft", "description": "Latest definition", "kind": "label"})
    assert edited.status_code == 200, edited.text

    seen = {}
    def fake_review(*, preset_revision, **_kwargs):
        seen["labels"] = preset_revision["configuration"]["shared_labels"]
        return {"review": {"review_kind": "pass_recovery", "steps": [], "episodes": []},
                "usage": {"kind": "saved_replay", "estimated_usd": 0, "billed": False},
                "provenance": {"new_inference": False}, "proposals": []}

    monkeypatch.setattr(queue, "SessionLocal", app_clients["factory"])
    monkeypatch.setattr(queue, "settings", replace(queue.settings, object_store_backend="local",
        local_artifact_dir=app_clients["tmp_path"] / "snapshot-worker-artifacts"))
    monkeypatch.setattr(review_backends, "execute_review", fake_review)
    with app_clients["factory"]() as db:
        job = db.scalar(select(Job).where(Job.batch_id == batch["id"]))
        job_id, generation = job.id, job.generation
    assert queue.run_review.run(job_id, generation)["status"] == "completed"
    labels = seen["labels"]
    assert any(item["id"] == "pinned-label" for item in labels)
    assert not any(item["id"] == "latest-only" for item in labels)
    assert any(item.get("proposal_id") == proposal["id"] and item["name"] == "Fresh draft" for item in labels)
    with app_clients["factory"]() as db:
        result = db.scalar(select(ReviewResult))
        assert result.provenance["taxonomy_release_id"] == pinned_id
        assert result.provenance["shared_labels_snapshot"] == labels


def test_worker_keeps_known_usage_when_artifact_publication_fails(app_clients, monkeypatch):
    from app import queue, review_backends

    client = app_clients["admin"]
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task(outcome="passed")).status_code == 200
    preset = create_saved_preset(client)
    batch = create_batch(client, dataset, preset, task_ids=["task-1"])
    assert post(client, f"/api/batches/{batch['id']}/start", json={}).status_code == 200
    with app_clients["factory"]() as db:
        job = db.scalar(select(Job))
        job_id, generation = job.id, job.generation

    monkeypatch.setattr(queue, "SessionLocal", app_clients["factory"])
    monkeypatch.setattr(queue, "settings", replace(queue.settings, object_store_backend="local",
        local_artifact_dir=app_clients["tmp_path"] / "failed-publication-artifacts"))
    monkeypatch.setattr(review_backends, "execute_review", lambda **_kwargs: {
        "review": {"review_kind": "pass_recovery", "steps": [], "episodes": []},
        "usage": {"kind": "provider_reported_tokens", "estimated_usd": 0.0123, "billed": True},
        "provenance": {}, "proposals": []})

    class FailingStore:
        def put(self, *_args):
            raise OSError("fixture storage failure")

    monkeypatch.setattr(queue, "create_artifact_store", lambda _settings: FailingStore())
    result = queue.run_review.run(job_id, generation)
    assert result["status"] == "failed"
    with app_clients["factory"]() as db:
        job = db.get(Job, job_id)
        attempt = db.scalar(select(queue.JobAttempt).where(queue.JobAttempt.job_id == job_id))
        assert job.usage["estimated_usd"] == 0.0123 and job.cost_usd == 0.0123
        assert attempt.usage["estimated_usd"] == 0.0123 and attempt.cost_usd == 0.0123


def test_cookie_mutations_reject_cross_origin(app_clients):
    client = app_clients["admin"]
    response = client.post("/api/teams", headers={"Origin": "http://attacker.invalid"},
                           json={"name": "Cross origin"})
    assert response.status_code == 403


def test_spa_fallback_serves_built_assets_and_rejects_missing_assets(app_clients):
    dist = app_clients["tmp_path"] / "platform" / "web" / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html></html>")
    (assets / "app-test.js").write_text("console.log('built asset')")

    root = app_clients["admin"].get("/")
    asset = app_clients["admin"].get("/assets/app-test.js")
    missing = app_clients["admin"].get("/assets/missing.js")
    api_missing = app_clients["admin"].get("/api/missing.js")

    assert root.status_code == 200 and root.headers["content-type"].startswith("text/html")
    assert asset.status_code == 200 and asset.headers["content-type"].startswith("text/javascript")
    assert asset.text == "console.log('built asset')"
    assert missing.status_code == api_missing.status_code == 404


def test_import_validates_steps_and_never_trusts_imported_screenshot_urls(app_clients):
    client = app_clients['admin']
    dataset = create_dataset(client)
    broken = task()
    broken['steps'] = [12]
    assert import_tasks(client, dataset['id'], broken).status_code == 422
    source = task()
    source['steps'][0]['screenshot_url'] = 'https://example.invalid/untrusted-image'
    assert import_tasks(client, dataset['id'], source).status_code == 200
    detail = client.get(f"/api/datasets/{dataset['id']}")
    assert detail.status_code == 200
    assert 'screenshot_url' not in detail.json()['tasks'][0]['steps'][0]


def signup_user(email):
    client = TestClient(main.app)
    response = post(client, "/api/auth/signup", json={"name": email.split("@")[0], "email": email,
                                                      "password": "member-password"})
    assert response.status_code == 200, response.text
    return client, response.json()


def create_saved_run(client, dataset):
    response = post(client, "/api/runs", json={"name": "Saved run", "dataset_ids": [dataset["id"]],
        "execution": {"backend": "saved_replay", "model": None, "budget_usd": 0, "configuration": {}}})
    assert response.status_code == 200, response.text
    return response.json()


def test_audit_events_record_ids_of_newly_created_objects(app_clients):
    from app.models import ActivityEvent

    client = app_clients["admin"]
    team = post(client, "/api/teams", json={"name": "Audited team"}).json()
    dataset = create_dataset(client, "Audited dataset")
    post(client, "/api/taxonomy/proposals", json={"name": "Wrong target", "description": "Clicked the neighbour."})
    candidate = post(client, "/api/taxonomy/consolidate", json={}).json()
    release = post(client, f"/api/taxonomy/candidates/{candidate['id']}/approve",
                   json={"expected_hash": candidate["hash"], "version": candidate["version"]})
    assert release.status_code == 200, release.text
    with app_clients["factory"]() as db:
        recorded = {row.action: row.object_id for row in db.scalars(select(ActivityEvent)).all()}
    assert recorded["team.created"] == team["id"]
    assert recorded["dataset.created"] == dataset["id"]
    assert recorded["taxonomy.consolidated"] == candidate["id"]
    assert recorded["taxonomy.approved"] == release.json()["id"]


def test_rerun_keeps_grant_roles_and_skips_deactivated_users(app_clients):
    client = app_clients["admin"]
    dataset = create_dataset(client)
    assert import_tasks(client, dataset["id"], task()).status_code == 200
    run = create_saved_run(client, dataset)
    viewer, viewer_user = signup_user("grant-viewer@example.test")
    _gone, gone_user = signup_user("grant-gone@example.test")
    for user in (viewer_user, gone_user):
        granted = post(client, f"/api/runs/{run['id']}/grants", json={"user_id": user["id"], "role": "viewer"})
        assert granted.status_code == 200, granted.text
    assert client.patch(f"/api/users/{gone_user['id']}", headers=ORIGIN, json={"active": False}).status_code == 200

    rerun = post(client, f"/api/runs/{run['id']}/rerun", json={})
    assert rerun.status_code == 200, rerun.text
    with app_clients["factory"]() as db:
        from app.models import BatchGrant
        grants = {(row.user_id, row.role) for row in db.scalars(
            select(BatchGrant).where(BatchGrant.batch_id == rerun.json()["id"])).all()}
    assert grants == {(viewer_user["id"], "viewer")}
    feedback = post(viewer, f"/api/runs/{rerun.json()['id']}/tasks/task-1/feedback", json={"text": "Viewer note"})
    assert feedback.status_code == 403


def test_list_endpoints_reject_non_positive_pagination(app_clients):
    client = app_clients["admin"]
    for path in ("/api/users", "/api/teams", "/api/datasets", "/api/presets", "/api/runs",
                 "/api/batches", "/api/jobs", "/api/activity"):
        assert client.get(path, params={"page": 0}).status_code == 422, path
        assert client.get(path, params={"per_page": -1}).status_code == 422, path
    for index in range(3):
        post(client, "/api/teams", json={"name": f"Paged team {index}"})
    oversized = client.get("/api/teams", params={"page": 2, "per_page": 1000}).json()
    assert oversized["total"] == 3 and oversized["items"] == []


def test_json_import_registers_only_bundled_images_as_evidence(app_clients):
    client = app_clients["admin"]
    poc = app_clients["tmp_path"] / "poc"
    for relative, body in (("runs/stderr.log", b"internal log line"),
                           ("viewer/index.html", b"<script>alert(1)</script>"),
                           ("data/source/fixture/fake.png", b"<html>not an image</html>"),
                           ("data/source/fixture/real.png", PNG_BYTES)):
        (poc / relative).parent.mkdir(parents=True, exist_ok=True)
        (poc / relative).write_bytes(body)
    dataset = create_dataset(client)
    imported = import_tasks(client, dataset["id"], task("log", screenshot="runs/stderr.log"),
                            task("html", screenshot="viewer/index.html"),
                            task("fake", screenshot="data/source/fixture/fake.png"),
                            task("real", screenshot="data/source/fixture/real.png"))
    assert imported.status_code == 200, imported.text
    steps = {item["task_id"]: item["steps"][0] for item in client.get(f"/api/datasets/{dataset['id']}").json()["tasks"]}
    assert not any(steps[name].get("screenshot_url") for name in ("log", "html", "fake"))
    image = client.get(steps["real"]["screenshot_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"


def test_presets_apply_run_execution_bounds_and_reject_secrets(app_clients):
    client = app_clients["admin"]
    base = {"name": "Bounded preset", "backend": "litellm", "model": "openai/gpt-test", "budget_usd": 0.25}
    for change in ({"configuration": {"api_key": "sk-live-SECRET"}},
                   {"configuration": {"nested": {"Authorization": "Bearer x"}}},
                   {"configuration": {"timeout_seconds": 100000}},
                   {"configuration": {"max_images": 10000}},
                   {"budget_usd": 99}):
        response = post(client, "/api/presets", json={**base, **change})
        assert response.status_code == 422, change
    assert "sk-live-SECRET" not in client.get("/api/presets").text
    assert post(client, "/api/presets", json={**base, "configuration": {"max_images": 8}}).status_code == 200


def test_proposal_label_ids_stay_unique_and_base_release_must_exist(app_clients):
    client = app_clients["admin"]
    assert post(client, "/api/taxonomy/proposals", json={"name": "A", "description": "a", "label_id": "L1"}).status_code == 200
    second = post(client, "/api/taxonomy/proposals", json={"name": "B", "description": "b", "label_id": "L2"}).json()
    duplicate = client.patch(f"/api/taxonomy/proposals/{second['id']}", headers=ORIGIN,
                             json={"name": "B", "description": "b", "label_id": "L1"})
    assert duplicate.status_code == 409
    same_label = client.patch(f"/api/taxonomy/proposals/{second['id']}", headers=ORIGIN,
                              json={"name": "B2", "description": "b", "label_id": "L2"})
    assert same_label.status_code == 200, same_label.text
    unknown = post(client, "/api/taxonomy/proposals", json={"name": "C", "description": "c",
                                                           "base_release_id": "missing-release"})
    assert unknown.status_code == 404


def test_team_member_emails_are_limited_to_admins_and_managers(app_clients):
    client = app_clients["admin"]
    viewer, _viewer_user = signup_user("team-viewer@example.test")
    _member, member_user = signup_user("team-member@example.test")
    team = post(client, "/api/teams", json={"name": "Email team"}).json()
    assert post(client, f"/api/teams/{team['id']}/members", json={"user_id": member_user["id"]}).status_code == 200
    viewer_members = viewer.get("/api/teams").json()["items"][0]["members"]
    assert viewer_members and all(item["email"] is None and item["name"] for item in viewer_members)
    admin_members = client.get("/api/teams").json()["items"][0]["members"]
    assert {item["email"] for item in admin_members} == {"team-member@example.test"}


def test_admin_cannot_deactivate_own_account(app_clients):
    client = app_clients["admin"]
    me = client.get("/api/auth/me").json()
    response = client.patch(f"/api/users/{me['id']}", headers=ORIGIN, json={"active": False})
    assert response.status_code == 409
    assert client.get("/api/auth/me").status_code == 200


def test_login_verifies_a_password_hash_even_for_unknown_emails(app_clients, monkeypatch):
    checked = []
    original = main.verify_password
    monkeypatch.setattr(main, "verify_password", lambda password, encoded: checked.append(encoded) or original(password, encoded))
    anonymous = TestClient(main.app)
    response = post(anonymous, "/api/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"})
    assert response.status_code == 401
    assert checked == [main.DUMMY_PASSWORD_HASH]


def test_request_body_cap_rejects_declared_and_streamed_oversize(app_clients, monkeypatch):
    monkeypatch.setattr(main, "MAX_REQUEST_BYTES", 1024)
    anonymous = TestClient(main.app)
    declared = anonymous.post("/api/auth/login", headers=ORIGIN, content=b"x" * 2048)
    assert declared.status_code == 413

    def chunks():
        for _ in range(4):
            yield b"y" * 512

    streamed = anonymous.post("/api/auth/login", headers={**ORIGIN, "Content-Type": "application/json"},
                              content=chunks())
    assert streamed.status_code == 413
    small = post(anonymous, "/api/auth/login", json={"email": "nobody@example.test", "password": "wrong-password"})
    assert small.status_code == 401


def test_lifespan_runs_startup_and_shutdown(monkeypatch):
    calls = []

    async def fake_shutdown():
        calls.append("shutdown")

    monkeypatch.setattr(main, "startup", lambda: calls.append("startup"))
    monkeypatch.setattr(main, "shutdown", fake_shutdown)
    with TestClient(main.app):
        assert calls == ["startup"]
    assert calls == ["startup", "shutdown"]
