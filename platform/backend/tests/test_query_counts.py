"""List and summary endpoints must not issue queries per task, member, job or attempt."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app import main
from app.database import make_engine, make_session_factory, session_dependency
from app.models import Batch, BatchMember, Job, JobAttempt, ObjectArchive, ReviewResult, utcnow


ORIGIN = {"Origin": "http://testserver"}
SLACK = 3


def post(client, path, body=None):
    response = client.post(path, headers=ORIGIN, json=body)
    assert response.status_code == 200, response.text
    return response.json()


@contextmanager
def workspace(tmp_path, monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    factory = make_session_factory(engine)
    main.init_db(engine)
    with monkeypatch.context() as patch:
        patch.setattr(main, "engine", engine)
        patch.setattr(main, "SessionLocal", factory)
        patch.setattr(main, "settings", replace(main.settings, seed_poc=False,
            object_store_backend="local", local_artifact_dir=tmp_path / "artifacts"))
        patch.setattr(main, "PROJECT_ROOT", tmp_path)
        patch.setitem(main.app.dependency_overrides, main.get_db, session_dependency(factory))
        # Without a context manager the client skips app startup (seeding, outbox relay).
        admin = TestClient(main.app)
        post(admin, "/api/auth/signup", {"name": "Admin", "email": "admin@example.test",
                                         "password": "test-password-123"})
        yield admin, factory, engine
    engine.dispose()


def seed(admin, factory, task_count):
    dataset = post(admin, "/api/datasets", {"name": "Scale fixture"})
    tasks = [{"task_id": f"task-{index}", "title": f"Task {index}", "instruction": "Review",
              "outcome": "failed" if index % 2 else "passed", "score": index % 2,
              "source": {"dataset": "fixture"},
              "steps": [{"step_id": "1", "action": "click", "observation": "seen", "evidence_refs": []}]}
             for index in range(task_count)]
    post(admin, f"/api/datasets/{dataset['id']}/import", {"format": "cuautoreview", "tasks": tasks})
    runs = [post(admin, "/api/runs", {"name": f"Run {index}", "dataset_ids": [dataset["id"]],
                                      "execution": {"backend": "saved_replay", "budget_usd": 0}})
            for index in range(2)]
    post(admin, f"/api/runs/{runs[0]['id']}/start", {})
    with factory() as db:
        for member in db.scalars(select(BatchMember).where(BatchMember.batch_id == runs[1]["id"])).all():
            batch = db.get(Batch, member.batch_id)
            for revision in (1, 2):
                db.add(ReviewResult(member_id=member.id, revision=revision, review_kind="failure_analysis",
                    source_kind="generated", backend="model_api", model="fixture",
                    review={"steps": [], "episodes": [{"episode_id": "e1", "label_id": "L1",
                            "onset_step_ids": ["1"], "recovery": {"step_ids": ["1"]}}]}))
            job = Job(workspace_id=batch.workspace_id, batch_id=batch.id, member_id=member.id,
                      review_kind="failure_analysis", preset_revision_id=batch.preset_revision_id,
                      idempotency_key=f"scale:{member.id}", status="completed", attempt_count=2)
            db.add(job)
            db.flush()
            db.add_all([JobAttempt(job_id=job.id, attempt_number=number, generation=1, fence_token=number,
                                   status="completed", cost_usd=0.01 if number == 1 else None)
                        for number in (1, 2)])
        db.commit()
    definition_id = admin.get(f"/api/datasets/{dataset['id']}").json()["tasks"][0]["task_definition_id"]
    return dataset, runs, definition_id


def query_counts(admin, engine, dataset, runs, definition_id):
    count = [0]

    def before_cursor_execute(*_args):
        count[0] += 1

    requests = {
        "catalog": lambda: admin.get("/api/catalog"),
        "datasets": lambda: admin.get("/api/datasets"),
        "dataset_detail": lambda: admin.get(f"/api/datasets/{dataset['id']}"),
        "task_history": lambda: admin.get(f"/api/datasets/{dataset['id']}/tasks/{definition_id}"),
        "overview": lambda: admin.get("/api/overview"),
        "runs": lambda: admin.get("/api/runs"),
        "run_detail": lambda: admin.get(f"/api/runs/{runs[1]['id']}"),
        "run_tasks": lambda: admin.get(f"/api/runs/{runs[1]['id']}/tasks"),
        "jobs": lambda: admin.get("/api/jobs"),
        "analytics": lambda: admin.post("/api/analytics/query", headers=ORIGIN, json={}),
    }
    counts = {}
    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        for name, request in requests.items():
            count[0] = 0
            response = request()
            assert response.status_code == 200, (name, response.text)
            counts[name] = count[0]
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return counts


def test_read_endpoint_queries_do_not_grow_with_task_count(tmp_path, monkeypatch):
    measured = {}
    for task_count in (6, 30):
        with workspace(tmp_path / str(task_count), monkeypatch) as (admin, factory, engine):
            dataset, runs, definition_id = seed(admin, factory, task_count)
            run_tasks = admin.get(f"/api/runs/{runs[1]['id']}/tasks").json()
            assert run_tasks["total"] == task_count
            assert all(len(item["review_history"]) == 2 for item in run_tasks["items"])
            measured[task_count] = query_counts(admin, engine, dataset, runs, definition_id)
            # Bulk loading must not widen access: a new viewer still sees nothing.
            viewer = TestClient(main.app)
            post(viewer, "/api/auth/signup", {"name": "Viewer", "email": "viewer@example.test",
                                              "password": "viewer-password-123"})
            catalog = viewer.get("/api/catalog").json()
            assert catalog == {"datasets": [], "runs": [], "tasks": []}
            assert viewer.get(f"/api/datasets/{dataset['id']}").status_code == 403
            assert viewer.get(f"/api/runs/{runs[1]['id']}").status_code == 403
            assert viewer.get("/api/jobs").json()["total"] == 0
            assert viewer.post("/api/analytics/query", headers=ORIGIN, json={}).json()["rows"] == []
    small, large = measured[6], measured[30]
    for name in small:
        assert large[name] <= small[name] + SLACK, (name, small[name], large[name])


def test_read_cache_is_dropped_when_the_session_writes(tmp_path, monkeypatch):
    with workspace(tmp_path, monkeypatch) as (admin, factory, _engine):
        dataset = post(admin, "/api/datasets", {"name": "Cache fixture"})
        with factory() as db:
            assert not main.is_archived(db, "dataset", dataset["id"])
            db.add(ObjectArchive(workspace_id=dataset["workspace_id"], object_type="dataset",
                                 object_id=dataset["id"], archived_at=utcnow()))
            db.flush()
            assert main.is_archived(db, "dataset", dataset["id"])
            db.rollback()
            assert not main.is_archived(db, "dataset", dataset["id"])
