"""Regression tests for relay fairness, stranded dispatch and storage recovery."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Job, JobAttempt, OutboxEvent, ReviewResult, utcnow
from test_batch_status import batch_app, job_records, make_batch, post, success, worker  # noqa: F401


def relay(app_state, monkeypatch):
    from app import queue

    monkeypatch.setattr(queue, "SessionLocal", app_state["factory"])
    sent = []
    monkeypatch.setattr(queue.run_review, "apply_async", lambda **kwargs: sent.append(kwargs))
    return queue.relay_outbox.run, sent


def event_for(db, job_id):
    return db.scalar(select(OutboxEvent).where(OutboxEvent.job_id == job_id))


def second_batch(client):
    dataset = post(client, "/api/datasets", {"name": "Second fixture", "description": ""}).json()
    assert post(client, f"/api/datasets/{dataset['id']}/import", {"format": "cuautoreview", "tasks": [{
        "task_id": "task-b", "title": "Task B", "instruction": "Review", "outcome": "passed", "score": 1,
        "source": {"dataset": "fixture"}, "steps": []}]}).status_code == 200
    preset = post(client, "/api/presets", {"name": "Saved second", "backend": "saved_replay", "model": None,
                                           "reasoning": "none", "budget_usd": 0, "configuration": {}}).json()
    response = post(client, "/api/batches", {"dataset_id": dataset["id"], "name": "Second fixture",
                                             "mode": "fixed", "preset_id": preset["id"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_paused_batch_backlog_does_not_starve_running_batches(batch_app, monkeypatch):
    client = batch_app["client"]
    paused = make_batch(client, "passed", "passed", "passed")
    assert post(client, f"/api/batches/{paused['id']}/start", {}).status_code == 200
    assert post(client, f"/api/batches/{paused['id']}/pause", {}).status_code == 200
    running = second_batch(client)
    assert post(client, f"/api/batches/{running['id']}/start", {}).status_code == 200
    run_relay, sent = relay(batch_app, monkeypatch)

    # The relay window equals the paused backlog; the running batch must still dispatch.
    assert run_relay(limit=3)["sent"] == 1
    running_job, _ = job_records(batch_app, running["id"])[0]
    assert [call["args"][0] for call in sent] == [running_job]
    with batch_app["factory"]() as db:
        assert event_for(db, running_job).status == "sent"
        for job_id, _ in job_records(batch_app, paused["id"]):
            assert event_for(db, job_id).status == "pending"


def paid_review(**_kwargs):
    output = success()
    output["usage"] = {"kind": "provider_reported_tokens", "estimated_usd": 0.04, "billed": True}
    output["provenance"] = {"new_inference": True, "model": "fixture"}
    return output


class FlakyStore:
    def __init__(self, store, failures):
        self.store, self.failures, self.calls = store, failures, 0

    def put(self, *args):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("Conditional artifact write failed; existing objects were not overwritten")
        return self.store.put(*args)


def use_store(monkeypatch, app_state, failures):
    from app import queue
    from app.storage import LocalArtifactStore

    store = FlakyStore(LocalArtifactStore(app_state["tmp_path"] / "worker-artifacts"), failures)
    monkeypatch.setattr(queue, "create_artifact_store", lambda _settings: store)
    monkeypatch.setattr(queue.time, "sleep", lambda _seconds: None)
    return store


def test_transient_storage_error_is_retried_within_the_attempt(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    run = worker(batch_app, monkeypatch, paid_review)
    store = use_store(monkeypatch, batch_app, failures=2)

    assert run(job_id, generation)["status"] == "completed"
    assert store.calls == 3
    with batch_app["factory"]() as db:
        assert db.get(Job, job_id).attempt_count == 1


def test_storage_outage_keeps_paid_review_for_store_only_retry(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    job_id, generation = job_records(batch_app, batch["id"])[0]
    run = worker(batch_app, monkeypatch, paid_review)
    use_store(monkeypatch, batch_app, failures=99)

    assert run(job_id, generation)["status"] == "retrying"
    with batch_app["factory"]() as db:
        job = db.get(Job, job_id)
        first = db.scalar(select(JobAttempt).where(JobAttempt.job_id == job_id))
        assert first.cost_usd == 0.04 and first.usage["review_error_category"] == "storage_unavailable"
        assert first.usage["unsaved_review"]["review"]["review_kind"] == "pass_recovery"
        job.available_at = utcnow()  # the backoff has elapsed
        db.commit()

    def must_not_call_provider(**_kwargs):
        raise AssertionError("a stored-only retry must not pay for another inference")

    run = worker(batch_app, monkeypatch, must_not_call_provider)
    use_store(monkeypatch, batch_app, failures=0)
    assert run(job_id, generation)["status"] == "completed"
    with batch_app["factory"]() as db:
        attempts = db.scalars(select(JobAttempt).where(JobAttempt.job_id == job_id)
                              .order_by(JobAttempt.attempt_number)).all()
        assert [attempt.cost_usd for attempt in attempts] == [0.04, 0]
        assert "unsaved_review" not in attempts[0].usage
        assert attempts[0].usage["unsaved_review_stored_by_attempt_id"] == attempts[1].id
        result = db.scalar(select(ReviewResult).where(ReviewResult.job_id == job_id))
        assert result.provenance["usage"]["estimated_usd"] == 0.04
        assert result.provenance["recovered_from_attempt_id"] == attempts[0].id
        assert result.provenance["attempt_id"] == attempts[1].id


def test_stranded_sent_event_is_redispatched_only_after_later_work_was_claimed(batch_app, monkeypatch):
    client = batch_app["client"]
    batch = make_batch(client, "passed", "passed", "passed")
    assert post(client, f"/api/batches/{batch['id']}/start", {}).status_code == 200
    (lost, lost_generation), (claimed, claimed_generation), (backlog, _) = job_records(batch_app, batch["id"])
    run_relay, sent = relay(batch_app, monkeypatch)
    assert run_relay()["sent"] == 3
    with batch_app["factory"]() as db:
        old = utcnow() - timedelta(hours=3)
        event_for(db, lost).sent_at = old
        event_for(db, claimed).sent_at = old + timedelta(minutes=1)
        event_for(db, backlog).sent_at = old + timedelta(minutes=2)
        db.commit()

    # Ordinary backlog: nothing published later has been claimed, so nothing is resent.
    assert run_relay()["stranded_requeued"] == 0

    # The worker claims a later message while the first job stays queued: that message was lost.
    # The backlog job was published after the claimed one, so FIFO delivery has not reached it yet.
    run = worker(batch_app, monkeypatch, success)
    assert run(claimed, claimed_generation)["status"] == "completed"
    assert run_relay()["stranded_requeued"] == 1
    with batch_app["factory"]() as db:
        assert event_for(db, lost).status == "pending"
        assert event_for(db, backlog).status == "sent"
    sent.clear()
    assert run_relay()["sent"] == 1
    assert [call["args"][0] for call in sent] == [lost]

    # Duplicate delivery stays idempotent through the generation-fenced claim.
    assert run(lost, lost_generation)["status"] == "completed"
    assert run(lost, lost_generation)["status"] == "obsolete_or_not_claimable"
