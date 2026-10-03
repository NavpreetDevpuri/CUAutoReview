"""Job lists and the overview must follow the same run access rules as run pages."""

from __future__ import annotations

import pytest
from conftest import isolate
from fastapi.testclient import TestClient

from app import main

ORIGIN = {"Origin": "http://testserver"}


def post(client, path, body=None):
    response = client.post(path, headers=ORIGIN, json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def admin(tmp_path, monkeypatch):
    engine, _factory = isolate(tmp_path, monkeypatch)
    # Without a context manager the client skips app startup (seeding, outbox relay).
    client = TestClient(main.app)
    post(client, "/api/auth/signup", {"name": "Admin", "email": "admin@example.test", "password": "test-password-123"})
    yield client
    engine.dispose()


def dataset_with_task(admin, name):
    dataset = post(admin, "/api/datasets", {"name": name})
    post(
        admin,
        f"/api/datasets/{dataset['id']}/import",
        {
            "format": "cuautoreview",
            "tasks": [
                {
                    "task_id": f"{name}-task",
                    "title": name,
                    "instruction": "Review",
                    "outcome": "failed",
                    "score": 0,
                    "source": {"dataset": "fixture"},
                    "steps": [],
                }
            ],
        },
    )
    return dataset


def started_run(admin, name, dataset_ids):
    run = post(
        admin,
        "/api/runs",
        {"name": name, "dataset_ids": dataset_ids, "execution": {"backend": "saved_replay", "budget_usd": 0}},
    )
    post(admin, f"/api/runs/{run['id']}/start", {})
    return run


def signup(name):
    client = TestClient(main.app)
    user = post(
        client, "/api/auth/signup", {"name": name, "email": f"{name}@example.test", "password": f"{name}-password-123"}
    )
    return client, user


def test_dataset_share_reaches_jobs_and_overview_like_run_pages(admin):
    dataset_a = dataset_with_task(admin, "alpha")
    dataset_b = dataset_with_task(admin, "beta")
    run_a = started_run(admin, "Alpha run", [dataset_a["id"]])
    run_ab = started_run(admin, "Alpha and beta run", [dataset_a["id"], dataset_b["id"]])
    reviewer, reviewer_user = signup("reviewer")
    outsider, _outsider_user = signup("outsider")
    admin.patch(f"/api/users/{reviewer_user['id']}", headers=ORIGIN, json={"role": "reviewer"})
    admin.put(
        f"/api/datasets/{dataset_a['id']}/shares",
        headers=ORIGIN,
        json={"workspace_shared": False, "users": [{"target_id": reviewer_user["id"], "role": "viewer"}]},
    )

    # A multi-source run needs every source shared, so only the single-source run is visible.
    assert [run["id"] for run in reviewer.get("/api/runs").json()["items"]] == [run_a["id"]]
    jobs = reviewer.get("/api/jobs").json()
    assert jobs["total"] == 1 and {job["run_id"] for job in jobs["items"]} == {run_a["id"]}
    assert reviewer.get(f"/api/jobs/{jobs['items'][0]['id']}").status_code == 200
    overview = reviewer.get("/api/overview").json()
    assert overview["batches"] == 1
    assert [batch["id"] for batch in overview["recent_batches"]] == [run_a["id"]]
    assert sum(overview["jobs"].values()) == 1
    admin_jobs = admin.get("/api/jobs").json()["items"]
    hidden_job = next(job for job in admin_jobs if job["run_id"] == run_ab["id"])
    assert reviewer.get(f"/api/jobs/{hidden_job['id']}").status_code == 403

    # Users without a grant or share still see nothing.
    assert outsider.get("/api/jobs").json()["total"] == 0
    assert outsider.get("/api/overview").json()["batches"] == 0

    # Revoking the share removes the jobs again.
    admin.put(f"/api/datasets/{dataset_a['id']}/shares", headers=ORIGIN, json={"workspace_shared": False, "users": []})
    assert reviewer.get("/api/jobs").json()["total"] == 0
    assert reviewer.get("/api/overview").json()["batches"] == 0


def test_dataset_detail_reports_the_callers_access_role(admin):
    dataset = dataset_with_task(admin, "gamma")
    viewer, viewer_user = signup("viewer")
    lead, lead_user = signup("lead")
    outsider, _outsider_user = signup("stranger")
    admin.put(
        f"/api/datasets/{dataset['id']}/shares",
        headers=ORIGIN,
        json={
            "workspace_shared": False,
            "users": [
                {"target_id": viewer_user["id"], "role": "viewer"},
                {"target_id": lead_user["id"], "role": "manager"},
            ],
        },
    )

    assert admin.get(f"/api/datasets/{dataset['id']}").json()["access_role"] == "admin"
    assert lead.get(f"/api/datasets/{dataset['id']}").json()["access_role"] == "manager"
    assert lead.get(f"/api/datasets/{dataset['id']}/shares").status_code == 200
    # The UI hides sharing for this role; the server keeps refusing it either way.
    assert viewer.get(f"/api/datasets/{dataset['id']}").json()["access_role"] == "viewer"
    assert viewer.get(f"/api/datasets/{dataset['id']}/shares").status_code == 403
    assert outsider.get(f"/api/datasets/{dataset['id']}").status_code in (403, 404)
