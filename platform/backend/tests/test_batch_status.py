from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main
from app.database import make_engine, make_session_factory, session_dependency
from app.models import Batch, BatchMember, Job, JobAttempt, ReviewResult, TaskRevision


ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def batch_app(tmp_path, monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    main.init_db(engine)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "settings", replace(main.settings, seed_poc=False,
        object_store_backend="local", local_artifact_dir=tmp_path / "artifacts"))
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    dependency = main.get_db
    main.app.dependency_overrides[dependency] = session_dependency(factory)
    startup, shutdown = main.app.router.on_startup[:], main.app.router.on_shutdown[:]
    main.app.router.on_startup.clear()
    main.app.router.on_shutdown.clear()
    with TestClient(main.app) as client:
        response = client.post("/api/auth/signup", json={
            "name": "Admin", "email": "admin@example.test", "password": "test-password-123"})
        assert response.status_code == 200, response.text
        yield {"client": client, "factory": factory, "tmp_path": tmp_path}
    main.app.dependency_overrides.pop(dependency, None)
    main.app.router.on_startup[:] = startup
    main.app.router.on_shutdown[:] = shutdown
    engine.dispose()


def post(client, path, body=None):
    return client.post(path, headers=ORIGIN, json=body)


def make_batch(client, *outcomes):
    dataset = post(client, "/api/datasets", {"name": "Status fixture", "description": ""}).json()
    tasks = [{"task_id": f"task-{index}", "title": f"Task {index}", "instruction": "Review",
        "outcome": outcome, "score": 1 if outcome == "passed" else 0,
        "source": {"dataset": "fixture"}, "steps": []}
        for index, outcome in enumerate(outcomes, start=1)]
    imported = post(client, f"/api/datasets/{dataset['id']}/import", {
        "format": "cuautoreview", "tasks": tasks})
    assert imported.status_code == 200, imported.text
    preset = post(client, "/api/presets", {"name": "Saved fixture", "backend": "saved_replay",
        "model": None, "reasoning": "none", "budget_usd": 0, "configuration": {}})
    assert preset.status_code == 200, preset.text
    response = post(client, "/api/batches", {"dataset_id": dataset["id"],
        "name": "Status fixture", "mode": "fixed", "preset_id": preset.json()["id"]})
    assert response.status_code == 200, response.text
    return response.json()


def worker(app_state, monkeypatch, execute_review):
    from app import queue, review_backends

    monkeypatch.setattr(queue, "SessionLocal", app_state["factory"])
    monkeypatch.setattr(queue, "settings", replace(queue.settings,
        object_store_backend="local", local_artifact_dir=app_state["tmp_path"] / "worker-artifacts"))
    monkeypatch.setattr(review_backends, "execute_review", execute_review)
    return queue.run_review.run


def success(**_kwargs):
    return {"review": {"review_kind": "pass_recovery", "steps": [], "episodes": []},
        "usage": {"kind": "saved_replay", "estimated_usd": 0, "billed": False},
        "provenance": {"new_inference": False}, "proposals": []}


def batch_record(app_state, batch_id):
    with app_state["factory"]() as db:
        return db.get(Batch, batch_id)


def job_records(app_state, batch_id):
    with app_state["factory"]() as db:
        return [(job.id, job.generation) for job in db.scalars(
            select(Job).where(Job.batch_id == batch_id).order_by(Job.created_at)).all()]


def test_last_of_two_worker_completions_settles_batch(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed", "passed")
    started = post(client, f"/api/batches/{batch['id']}/start", {})
    assert started.status_code == 200 and started.json()["status"] == "running"
    jobs = job_records(batch_app, batch["id"])
    run = worker(batch_app, monkeypatch, success)

    assert run(*jobs[0])["status"] == "completed"
    middle = client.get(f"/api/batches/{batch['id']}").json()
    assert middle["status"] == "running"
    assert middle["progress"]["completed"] == 1

    assert run(*jobs[1])["status"] == "completed"
    final = client.get(f"/api/batches/{batch['id']}").json()
    assert final["status"] == "completed"
    assert final["progress"]["completed"] == final["progress"]["total"] == 2


def test_failure_settles_and_retry_reopens_batch(batch_app, monkeypatch):
    from app.review_backends import ReviewBackendError

    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    calls = 0

    def fail_once(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ReviewBackendError("fixture failure", usage={"kind": "unknown", "estimated_usd": None})
        return success()

    run = worker(batch_app, monkeypatch, fail_once)
    assert run(job_id, generation)["status"] == "failed"
    failed = client.get(f"/api/batches/{batch['id']}").json()
    assert failed["status"] == "completed"
    assert failed["progress"]["failed"] == 1

    retried = post(client, f"/api/jobs/{job_id}/retry", {})
    assert retried.status_code == 200 and retried.json()["generation"] == generation + 1
    assert client.get(f"/api/batches/{batch['id']}").json()["status"] == "running"
    assert run(job_id, generation + 1)["status"] == "completed"
    final = client.get(f"/api/batches/{batch['id']}").json()
    assert final["status"] == "completed"
    assert final["progress"]["completed"] == 1


def test_retryable_provider_output_failures_are_bounded_and_keep_attempt_costs(batch_app, monkeypatch):
    from datetime import timedelta
    from app import queue
    from app.review_backends import ReviewBackendError

    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    calls = 0

    def malformed_then_success(**_kwargs):
        nonlocal calls
        calls += 1
        if calls <= 3:
            usage = {"estimated_usd": 0.01, "review_error_category": "model_response_schema_invalid"}
            if calls == 2:
                usage["estimated_usd"] = None
            raise ReviewBackendError("Output failed evidence/schema validation", usage=usage)
        return success()

    monkeypatch.setattr(queue, "_retry_delay", lambda _attempt: timedelta(seconds=0))
    run = worker(batch_app, monkeypatch, malformed_then_success)
    assert run(job_id, generation)["status"] == "retrying"
    assert run(job_id, generation)["status"] == "retrying"
    assert run(job_id, generation)["status"] == "retrying"
    assert run(job_id, generation)["status"] == "completed"

    detail = client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["attempt_count"] == body["max_attempts"] == 4
    assert [attempt["status"] for attempt in body["attempts"]] == ["failed", "failed", "failed", "completed"]
    assert body["cumulative_cost_usd"] == pytest.approx(0.02)
    assert body["unknown_cost_attempts"] == 1
    assert body["retry_eligible"] is False
    assert len(body["attempts"]) == 4
    with batch_app["factory"]() as db:
        member = db.scalar(select(BatchMember).where(BatchMember.batch_id == batch["id"]))
        assert len(db.scalars(select(ReviewResult).where(ReviewResult.member_id == member.id)).all()) == 1
    exhausted = post(client, f"/api/jobs/{job_id}/retry", {})
    assert exhausted.status_code == 409


def test_deterministic_auth_failure_is_terminal_without_automatic_retry(batch_app, monkeypatch):
    from app.review_backends import ReviewBackendError

    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    calls = 0

    def auth_failure(**_kwargs):
        nonlocal calls
        calls += 1
        raise ReviewBackendError("Provider authentication failed", usage={
            "estimated_usd": None, "cli_diagnostic_category": "provider_auth_failed"})

    run = worker(batch_app, monkeypatch, auth_failure)
    assert run(job_id, generation)["status"] == "failed"
    assert calls == 1
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed" and job["attempt_count"] == 1
    assert job["max_attempts"] == 4 and job["attempts"][0]["status"] == "failed"
    assert job["error"] and "authentication" in job["error"].lower()


def test_retryable_failure_stops_after_four_total_attempts(batch_app, monkeypatch):
    from datetime import timedelta
    from app import queue
    from app.review_backends import ReviewBackendError

    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    calls = 0

    def always_malformed(**_kwargs):
        nonlocal calls
        calls += 1
        raise ReviewBackendError("Model response failed schema validation", usage={
            "estimated_usd": 0.01, "review_error_category": "model_response_schema_invalid"})

    monkeypatch.setattr(queue, "_retry_delay", lambda _attempt: timedelta(seconds=0))
    run = worker(batch_app, monkeypatch, always_malformed)
    assert run(job_id, generation)["status"] == "retrying"
    assert run(job_id, generation)["status"] == "retrying"
    assert run(job_id, generation)["status"] == "retrying"
    assert run(job_id, generation)["status"] == "failed"
    assert run(job_id, generation)["status"] == "obsolete_or_not_claimable"
    assert calls == 4
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["attempt_count"] == job["max_attempts"] == len(job["attempts"]) == 4
    assert [attempt["status"] for attempt in job["attempts"]] == ["failed"] * 4
    assert job["cumulative_cost_usd"] == pytest.approx(0.04)
    assert job["unknown_cost_attempts"] == 0
    assert post(client, f"/api/jobs/{job_id}/retry", {}).status_code == 409


def test_dataset_task_summaries_separate_benchmark_status_and_reviews(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    with batch_app["factory"]() as db:
        member = db.scalar(select(BatchMember).where(BatchMember.batch_id == batch["id"]))
        revision = db.get(TaskRevision, member.task_revision_id)
        revision.content = {**revision.content, "steps": [
            {"step_id": "step-1", "screenshot": "shot-1.png"},
            {"step_id": "step-2", "screenshot_path": "shot-2.png"}]}
        db.commit()

    def reviewed(**_kwargs):
        return {"review": {"review_kind": "pass_recovery", "steps": [], "episodes": [{
            "episode_id": "problem-1", "label_id": "navigation", "label_name": "Navigation",
            "onset_step_ids": ["step-1"], "recovery": {"step_ids": ["step-2"]}}]},
            "usage": {"kind": "provider_reported_tokens", "estimated_usd": 0.02},
            "provenance": {"backend": "fixture", "model": "fixture-v1", "new_inference": True,
                "evidence_mode": "images", "source_image_step_ids": ["step-1", "step-2"],
                "supplied_image_step_ids": ["step-1"], "omitted_image_step_ids": ["step-2"],
                "cited_image_step_ids": ["step-1"], "image_selection": "all",
                "omitted_image_reason": "fixture capacity"}, "proposals": []}

    run = worker(batch_app, monkeypatch, reviewed)
    assert run(job_id, generation)["status"] == "completed"
    dataset = client.get(f"/api/datasets/{batch['dataset_id']}").json()
    task = dataset["tasks"][0]
    assert task["score"] == 1
    assert task["summary"]["run_count"] == task["summary"]["saved_review_count"] == 1
    assert task["summary"]["problem_count"] == 1
    assert task["summary"]["flagged_step_count"] == 1
    assert task["summary"]["recovery_step_count"] == 1
    assert task["summary"]["flagged_labels"] == [{"id": "navigation", "name": "Navigation", "count": 1}]
    assert task["summary"]["source_image_count"] == 2
    assert task["summary"]["supplied_image_count"] == 1
    assert task["summary"]["omitted_image_count"] == 1
    assert task["summary"]["cited_image_count"] == 1
    assert task["summary"]["models"][0]["backend"] == "saved_replay"

    detail = client.get(f"/api/datasets/{batch['dataset_id']}/tasks/{task['task_definition_id']}").json()
    run_row = detail["runs"][0]
    assert run_row["outcome"] == "passed" and run_row["score"] == 1
    assert run_row["status"] == "completed" and run_row["job_id"] == job_id
    assert run_row["review_summary"]["flagged_step_count"] == 1
    assert run_row["review_summary"]["evidence_mode"] == "images"
    assert run_row["review_provenance"]["supplied_image_step_ids"] == ["step-1"]
    assert run_row["jobs"][0]["attempts"][0]["status"] == "completed"
    assert detail["summary"]["models"][0]["current_review_count"] == 1


def test_analytics_separates_unknown_cost_jobs_from_attempts(batch_app):
    client = batch_app["client"]
    batch = make_batch(client, "failed")
    started = post(client, f"/api/batches/{batch['id']}/start", {})
    assert started.status_code == 200

    with batch_app["factory"]() as db:
        job = db.scalar(select(Job).where(Job.batch_id == batch["id"]))
        member = db.get(BatchMember, job.member_id)
        job.status = "failed"
        job.generation = 2
        job.attempt_count = 2
        member.status = "failed"
        for number in (1, 2):
            db.add(JobAttempt(job_id=job.id, attempt_number=number, generation=number,
                fence_token=number, status="failed",
                usage={"kind": "unknown", "estimated_usd": None}, cost_usd=None))
        db.commit()

    response = post(client, "/api/analytics/query", {"run_ids": [batch["id"]]})
    assert response.status_code == 200, response.text
    body = response.json()
    row = next(item for item in body["rows"] if item["run_id"] == batch["id"])
    assert row["unknown_cost_jobs"] == 1
    assert row["unknown_cost_attempts"] == 2
    assert body["counts"]["unknown_cost_jobs"] == 1
    assert body["counts"]["unknown_cost_attempts"] == 2
    assert body["counts"]["cost_usd"] is None


def test_worker_completion_does_not_overwrite_pause(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]

    def pause_during_review(**_kwargs):
        response = post(client, f"/api/batches/{batch['id']}/pause")
        assert response.status_code == 200, response.text
        return success()

    run = worker(batch_app, monkeypatch, pause_during_review)
    assert run(job_id, generation)["status"] == "completed"
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["status"] == "paused"
    assert detail["progress"]["completed"] == 1

    resumed = post(client, f"/api/batches/{batch['id']}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "completed"


def test_retry_while_paused_does_not_resume_dispatch(batch_app, monkeypatch):
    from app.review_backends import ReviewBackendError

    client = batch_app["client"]
    batch = make_batch(client, "passed", "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    jobs = job_records(batch_app, batch["id"])

    def fail(**_kwargs):
        raise ReviewBackendError("fixture failure", usage={"kind": "unknown", "estimated_usd": None})

    run = worker(batch_app, monkeypatch, fail)
    assert run(*jobs[0])["status"] == "failed"
    assert post(client, f"/api/batches/{batch['id']}/pause").status_code == 200

    retried = post(client, f"/api/jobs/{jobs[0][0]}/retry", {})
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["status"] == "paused"
    assert detail["progress"]["queued"] == 2


def test_cancel_fences_in_flight_worker_and_preserves_unknown_usage(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]

    def cancel_during_review(**_kwargs):
        response = post(client, f"/api/batches/{batch['id']}/cancel")
        assert response.status_code == 200, response.text
        return success()

    run = worker(batch_app, monkeypatch, cancel_during_review)
    assert run(job_id, generation)["status"] == "fence_lost"
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["status"] == "cancelled"
    assert detail["progress"]["status_counts"]["cancelled"] == 1
    with batch_app["factory"]() as db:
        job = db.get(Job, job_id)
        member = db.scalar(select(BatchMember).where(BatchMember.batch_id == batch["id"]))
        attempt = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
        assert job.status == member.status == attempt.status == "cancelled"
        assert job.usage == attempt.usage == {"kind": "unknown", "estimated_usd": None}
        assert db.scalar(select(ReviewResult).where(ReviewResult.member_id == member.id)) is None


def test_reconcile_is_explicit_and_uses_authoritative_member_and_job_state(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    run = worker(batch_app, monkeypatch, success)
    assert run(job_id, generation)["status"] == "completed"

    # Simulate a batch left stale by the pre-fix worker. A read reports persisted
    # status and never silently infers completion from its 100% member progress.
    with batch_app["factory"]() as db:
        db.get(Batch, batch["id"]).status = "running"
        db.commit()
    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["status"] == "running" and detail["progress"]["completed"] == 1

    repaired = post(client, f"/api/batches/{batch['id']}/reconcile")
    assert repaired.status_code == 200 and repaired.json()["reconciled"] is True
    assert repaired.json()["previous_status"] == "running"
    assert repaired.json()["status"] == "completed"
    repeated = post(client, f"/api/batches/{batch['id']}/reconcile")
    assert repeated.status_code == 200 and repeated.json()["reconciled"] is False


def test_reconcile_keeps_unknown_outcome_waiting_for_review(batch_app):
    client = batch_app["client"]
    batch = make_batch(client, "unknown")
    started = post(client, f"/api/batches/{batch['id']}/start", {})
    assert started.status_code == 200 and started.json()["status"] == "awaiting_review"
    with batch_app["factory"]() as db:
        db.get(Batch, batch["id"]).status = "running"
        db.commit()

    repaired = post(client, f"/api/batches/{batch['id']}/reconcile")
    assert repaired.status_code == 200 and repaired.json()["reconciled"] is True
    assert repaired.json()["status"] == "awaiting_review"
    assert repaired.json()["progress"]["awaiting_review"] == 1
