from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main
from app.database import make_engine, make_session_factory, session_dependency
from app.models import BatchMember, ReviewResult


ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def hierarchy_client(tmp_path, monkeypatch):
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
    with TestClient(main.app) as admin:
        response = admin.post("/api/auth/signup", headers=ORIGIN, json={"name": "Hierarchy Admin",
            "email": "hierarchy-admin@example.test", "password": "hierarchy-admin-password"})
        assert response.status_code == 200, response.text
        yield {"admin": admin, "factory": factory, "engine": engine}
    main.app.dependency_overrides.pop(dependency, None)
    main.app.router.on_startup[:] = startup
    main.app.router.on_shutdown[:] = shutdown
    engine.dispose()


def create_dataset(admin, name, task_id):
    dataset = admin.post("/api/datasets", headers=ORIGIN, json={"name": name}).json()
    task = {"task_id": task_id, "title": "Hierarchy fixture task", "instruction": "Inspect the page",
        "outcome": "passed", "steps": [{"step_id": "step-1", "action": "inspect",
        "observation": "No screenshot was supplied", "evidence_refs": []}]}
    imported = admin.post(f"/api/datasets/{dataset['id']}/import", headers=ORIGIN,
        json={"format": "cuautoreview", "tasks": [task]})
    assert imported.status_code == 200, imported.text
    detail = admin.get(f"/api/datasets/{dataset['id']}").json()
    return dataset, detail["tasks"][0]


def test_runs_shares_archives_catalog_analytics_and_comparison(hierarchy_client):
    admin = hierarchy_client["admin"]
    dataset_a, task_a = create_dataset(admin, "Hierarchy A", "task-a")
    dataset_b, task_b = create_dataset(admin, "Hierarchy B", "task-b")
    preset = admin.post("/api/presets", headers=ORIGIN, json={"name": "Hierarchy replay",
        "backend": "saved_replay", "reasoning": "none", "budget_usd": 0}).json()
    created = admin.post("/api/runs", headers=ORIGIN, json={"name": "Multi-source run",
        "dataset_ids": [dataset_a["id"], dataset_b["id"]], "workflow_revision_id": "trajectory_review@1",
        "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert created.status_code == 200, created.text
    run = created.json()
    assert len(run["source_datasets"]) == 2
    source_counts = {item["id"]: (item["task_count"], item["total_task_count"])
        for item in run["source_datasets"]}
    assert source_counts == {dataset_a["id"]: (1, 1), dataset_b["id"]: (1, 1)}
    assert run["progress"]["total"] == 2
    assert run["configuration"]["workflow_snapshot"]["revision_id"] == "trajectory_review@1"
    assert admin.get("/api/runs").json()["total"] == 1
    assert admin.get("/api/catalog").json()["runs"][0]["id"] == run["id"]
    run_tasks = admin.get(f"/api/runs/{run['id']}/tasks").json()["items"]
    assert {item["task_id"]: (item["task_definition_id"], item["dataset_id"]) for item in run_tasks} == {
        "task-a": (task_a["task_definition_id"], dataset_a["id"]),
        "task-b": (task_b["task_definition_id"], dataset_b["id"]),
    }

    viewer = TestClient(main.app)
    viewer_user = viewer.post("/api/auth/signup", headers=ORIGIN, json={"name": "Hierarchy Viewer",
        "email": "hierarchy-viewer@example.test", "password": "hierarchy-viewer-password"}).json()
    share_a = admin.put(f"/api/datasets/{dataset_a['id']}/shares", headers=ORIGIN,
        json={"workspace_shared": False, "users": [{"target_id": viewer_user["id"], "role": "viewer"}]})
    assert share_a.status_code == 200
    assert viewer.get(f"/api/datasets/{dataset_a['id']}").status_code == 200
    assert viewer.get(f"/api/datasets/{dataset_b['id']}").status_code == 403
    assert viewer.get(f"/api/runs/{run['id']}").status_code == 403
    assert viewer.get("/api/runs").json()["total"] == 0
    assert viewer.post("/api/analytics/query", headers=ORIGIN, json={"dataset_ids": [dataset_b["id"]]}).status_code == 404
    assert admin.post(f"/api/datasets/{dataset_a['id']}/archive", headers=ORIGIN).status_code == 200
    assert viewer.post(f"/api/datasets/{dataset_a['id']}/archive", headers=ORIGIN).status_code == 403
    assert admin.post(f"/api/datasets/{dataset_a['id']}/restore", headers=ORIGIN).status_code == 200
    assert admin.get("/api/directory?q=hierarchy-viewer").json()["users"][0]["id"] == viewer_user["id"]

    members = admin.get(f"/api/runs/{run['id']}/tasks").json()["items"]
    member_a = next(member for member in members if member["task_id"] == "task-a")
    with hierarchy_client["factory"]() as db:
        member = db.get(BatchMember, member_a["member_id"])
        review_one = {"review_kind": "pass_recovery", "steps": [], "episodes": [{"episode_id": "episode-1",
            "label_id": "label-a", "label_name": "Transient", "recovery": {"step_ids": ["step-1"]}}]}
        review_two = {"review_kind": "pass_recovery", "steps": [], "episodes": [{"episode_id": "episode-1",
            "label_id": "label-b", "label_name": "Misclick", "recovery": {"step_ids": ["step-1"]}}]}
        first = ReviewResult(member_id=member.id, revision=1, review_kind="pass_recovery", source_kind="generated",
            backend="model_api", model="fixture-model", review=review_one)
        second = ReviewResult(member_id=member.id, revision=2, review_kind="pass_recovery", source_kind="generated",
            backend="claude_code", model="fixture-cli", review=review_two)
        db.add_all([first, second])
        db.commit()
        result_ids = [first.id, second.id]

    task_history = admin.get(f"/api/datasets/{dataset_a['id']}/tasks/{task_a['task_definition_id']}")
    assert task_history.status_code == 200
    assert len(task_history.json()["runs"]) == 1
    assert len(task_history.json()["runs"][0]["reviews"]) == 2
    comparison = admin.post("/api/analytics/compare", headers=ORIGIN, json={"result_ids": result_ids})
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["verdict"] is None
    assert comparison.json()["aligned"]["task_id"] == "task-a"
    assert any(difference["field"] == "episodes" for difference in comparison.json()["differences"])
    assert all({"model", "backend", "review", "task_id"} <= result.keys() for result in comparison.json()["results"])
    assert comparison.json()["results"][0]["review"] == review_one
    assert viewer.post("/api/analytics/compare", headers=ORIGIN, json={"result_ids": result_ids}).status_code == 403

    admin.put(f"/api/datasets/{dataset_b['id']}/shares", headers=ORIGIN,
        json={"workspace_shared": False, "users": [{"target_id": viewer_user["id"], "role": "viewer"}]})
    assert viewer.get(f"/api/runs/{run['id']}").status_code == 200
    shared_compare = viewer.post("/api/analytics/compare", headers=ORIGIN, json={"result_ids": result_ids})
    assert shared_compare.status_code == 200, shared_compare.text

    analytics = admin.post("/api/analytics/query", headers=ORIGIN, json={"dataset_ids": [dataset_a["id"]],
        "run_ids": [run["id"]], "task_definition_ids": [task_a["task_definition_id"]]})
    assert analytics.status_code == 200, analytics.text
    report = analytics.json()
    assert report["counts"]["task_definitions"] == 1 and report["counts"]["run_members"] == 1
    assert report["counts"]["problem_episodes"] == 1
    assert report["counts"]["absent_frame_steps"] == 1
    assert report["rows"][0]["review_result_id"] is not None

    run_a_only = admin.post("/api/runs", headers=ORIGIN, json={"name": "Dataset A only",
        "dataset_ids": [dataset_a["id"]], "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert run_a_only.status_code == 200, run_a_only.text
    denominator_report = admin.post("/api/analytics/query", headers=ORIGIN, json={
        "dataset_ids": [dataset_a["id"], dataset_b["id"]], "run_ids": [run_a_only.json()["id"]],
        "task_definition_ids": [task_a["task_definition_id"], task_b["task_definition_id"]]})
    assert denominator_report.status_code == 200, denominator_report.text
    assert denominator_report.json()["counts"]["task_definitions"] == 1
    assert denominator_report.json()["counts"]["selected_task_definitions"] == 2
    assert denominator_report.json()["counts"]["run_members"] == 1

    run_b_only = admin.post("/api/runs", headers=ORIGIN, json={"name": "Dataset B only",
        "dataset_ids": [dataset_b["id"]], "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert run_b_only.status_code == 200, run_b_only.text
    empty_intersection = admin.post("/api/analytics/query", headers=ORIGIN, json={
        "dataset_ids": [dataset_a["id"]], "run_ids": [run_b_only.json()["id"]],
        "task_definition_ids": [task_a["task_definition_id"]]})
    assert empty_intersection.status_code == 200, empty_intersection.text
    assert empty_intersection.json()["counts"]["task_definitions"] == 0
    assert empty_intersection.json()["counts"]["selected_task_definitions"] == 1
    assert empty_intersection.json()["counts"]["run_members"] == 0
    assert empty_intersection.json()["rows"] == []

    source_task_revisions = {item["task_id"]: item["revision_id"]
        for item in admin.get(f"/api/runs/{run['id']}/tasks").json()["items"]}
    cancelled = admin.post(f"/api/runs/{run['id']}/cancel", headers=ORIGIN)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    rerun = admin.post(f"/api/runs/{run['id']}/rerun", headers=ORIGIN, json={})
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["id"] != run["id"]
    assert rerun.json()["configuration"]["rerun_of_run_id"] == run["id"]
    assert rerun.json()["status"] == "draft"
    rerun_task_revisions = {item["task_id"]: item["revision_id"]
        for item in admin.get(f"/api/runs/{rerun.json()['id']}/tasks").json()["items"]}
    assert rerun_task_revisions == source_task_revisions
    assert admin.get(f"/api/runs/{run['id']}").json()["status"] == "cancelled"
    archived_task = admin.post(f"/api/tasks/{task_b['task_definition_id']}/archive", headers=ORIGIN)
    assert archived_task.status_code == 200 and archived_task.json()["archived"] is True
    assert admin.get(f"/api/datasets/{dataset_b['id']}/tasks/{task_b['task_definition_id']}/export").status_code == 404
    assert admin.get(f"/api/datasets/{dataset_b['id']}/tasks/{task_b['task_definition_id']}/export?include_archived=true").status_code == 200
    assert task_b["task_definition_id"] not in [item["task_definition_id"] for item in admin.get("/api/catalog").json()["tasks"]]
    assert task_b["task_definition_id"] in [item["task_definition_id"] for item in admin.get("/api/catalog?include_archived=true").json()["tasks"]]
    assert admin.post(f"/api/tasks/{task_b['task_definition_id']}/restore", headers=ORIGIN).json()["archived"] is False

    assert admin.post(f"/api/datasets/{dataset_b['id']}/archive", headers=ORIGIN).json()["archived"] is True
    assert admin.get(f"/api/datasets/{dataset_b['id']}").status_code == 404
    assert admin.get(f"/api/datasets/{dataset_b['id']}?include_archived=true").status_code == 200
    admin.post(f"/api/datasets/{dataset_b['id']}/restore", headers=ORIGIN)
    assert admin.get(f"/api/datasets/{dataset_b['id']}/tasks/{task_b['task_definition_id']}/export").status_code == 200
    assert admin.post(f"/api/runs/{run['id']}/archive", headers=ORIGIN).json()["archived"] is True
    assert admin.get(f"/api/runs/{run['id']}").status_code == 404
    assert all(item["id"] != run["id"] for item in admin.get("/api/runs").json()["items"])
    assert any(item["id"] == run["id"] for item in admin.get("/api/runs?include_archived=true").json()["items"])
    assert admin.get(f"/api/runs/{run['id']}?include_archived=true").status_code == 200
    assert admin.post(f"/api/runs/{run['id']}/restore", headers=ORIGIN).json()["archived"] is False
    assert admin.get(f"/api/runs/{run['id']}").status_code == 200


def test_run_draft_cancel_rerun_and_archive_restore_authorization(hierarchy_client):
    admin = hierarchy_client["admin"]
    dataset, task = create_dataset(admin, "Lifecycle dataset", "lifecycle-task")
    created = admin.post("/api/runs", headers=ORIGIN, json={"name": "Lifecycle draft",
        "dataset_ids": [dataset["id"]], "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert created.status_code == 200, created.text
    original = created.json()
    assert original["status"] == "draft"

    viewer = TestClient(main.app)
    viewer_user = viewer.post("/api/auth/signup", headers=ORIGIN, json={"name": "Lifecycle Viewer",
        "email": "lifecycle-viewer@example.test", "password": "lifecycle-viewer-password"}).json()
    share = admin.put(f"/api/datasets/{dataset['id']}/shares", headers=ORIGIN,
        json={"users": [{"target_id": viewer_user["id"], "role": "viewer"}]})
    assert share.status_code == 200
    assert viewer.get(f"/api/runs/{original['id']}").status_code == 200
    for action, payload in (("cancel", None), ("archive", None), ("rerun", {}),
                            ("configure", {"execution": {"backend": "saved_replay", "budget_usd": 0}})):
        response = viewer.post(f"/api/runs/{original['id']}/{action}", headers=ORIGIN, json=payload)
        assert response.status_code == 403, f"viewer unexpectedly performed {action}: {response.text}"

    original_revision = admin.get(f"/api/runs/{original['id']}/tasks").json()["items"][0]["revision_id"]
    cancelled = admin.post(f"/api/runs/{original['id']}/cancel", headers=ORIGIN)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    rerun_response = admin.post(f"/api/runs/{original['id']}/rerun", headers=ORIGIN, json={})
    assert rerun_response.status_code == 200, rerun_response.text
    rerun = rerun_response.json()
    assert rerun["id"] != original["id"] and rerun["status"] == "draft"
    assert rerun["configuration"]["rerun_of_run_id"] == original["id"]
    assert admin.get(f"/api/runs/{rerun['id']}/tasks").json()["items"][0]["revision_id"] == original_revision
    assert admin.get(f"/api/runs/{original['id']}").json()["status"] == "cancelled"

    archived = admin.post(f"/api/runs/{original['id']}/archive", headers=ORIGIN)
    assert archived.status_code == 200 and archived.json()["archived"] is True
    assert admin.get(f"/api/runs/{original['id']}").status_code == 404
    assert all(item["id"] != original["id"] for item in admin.get("/api/runs").json()["items"])
    assert any(item["id"] == original["id"]
               for item in admin.get("/api/runs?include_archived=true").json()["items"])
    restored = admin.post(f"/api/runs/{original['id']}/restore", headers=ORIGIN)
    assert restored.status_code == 200 and restored.json()["archived"] is False
    assert admin.get(f"/api/runs/{original['id']}").status_code == 200


def test_analytics_run_and_dataset_filters_count_matched_tasks(hierarchy_client):
    admin = hierarchy_client["admin"]
    dataset_a, task_a = create_dataset(admin, "Filter A", "filter-a")
    dataset_b, task_b = create_dataset(admin, "Filter B", "filter-b")

    run_a = admin.post("/api/runs", headers=ORIGIN, json={"name": "Only A",
        "dataset_ids": [dataset_a["id"]], "execution": {"backend": "saved_replay", "budget_usd": 0}})
    run_b = admin.post("/api/runs", headers=ORIGIN, json={"name": "Only B",
        "dataset_ids": [dataset_b["id"]], "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert run_a.status_code == run_b.status_code == 200, (run_a.text, run_b.text)

    partial = admin.post("/api/analytics/query", headers=ORIGIN, json={
        "dataset_ids": [dataset_a["id"], dataset_b["id"]], "run_ids": [run_a.json()["id"]],
        "task_definition_ids": [task_a["task_definition_id"], task_b["task_definition_id"]]})
    assert partial.status_code == 200, partial.text
    assert partial.json()["counts"]["task_definitions"] == 1
    assert partial.json()["counts"]["selected_task_definitions"] == 2
    assert partial.json()["counts"]["run_members"] == 1
    assert len(partial.json()["rows"]) == 1
    assert partial.json()["rows"][0]["task_definition_id"] == task_a["task_definition_id"]

    empty = admin.post("/api/analytics/query", headers=ORIGIN, json={
        "dataset_ids": [dataset_a["id"]], "run_ids": [run_b.json()["id"]],
        "task_definition_ids": [task_a["task_definition_id"]]})
    assert empty.status_code == 200, empty.text
    assert empty.json()["filters"]["dataset_ids"] == [dataset_a["id"]]
    assert empty.json()["filters"]["run_ids"] == [run_b.json()["id"]]
    assert empty.json()["counts"]["task_definitions"] == 0
    assert empty.json()["counts"]["selected_task_definitions"] == 1
    assert empty.json()["counts"]["run_members"] == empty.json()["counts"]["rows"] == 0
    assert empty.json()["rows"] == []


def test_dataset_membership_coverage_is_scoped_to_each_source(hierarchy_client):
    admin = hierarchy_client["admin"]
    dataset_a, task_a = create_dataset(admin, "Coverage A", "coverage-a-1")
    dataset_b, task_b = create_dataset(admin, "Coverage B", "coverage-b-1")
    extra_task = {"task_id": "coverage-a-2", "title": "Second coverage task",
        "instruction": "Inspect the second fixture", "outcome": "passed", "steps": []}
    imported = admin.post(f"/api/datasets/{dataset_a['id']}/import", headers=ORIGIN,
        json={"format": "cuautoreview", "tasks": [extra_task]})
    assert imported.status_code == 200, imported.text

    created = admin.post("/api/runs", headers=ORIGIN, json={"name": "Coverage multi-source run",
        "task_definition_ids": [task_a["task_definition_id"], task_b["task_definition_id"]],
        "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]

    detail_a = admin.get(f"/api/datasets/{dataset_a['id']}").json()
    detail_b = admin.get(f"/api/datasets/{dataset_b['id']}").json()
    assert detail_a["membership_coverage"] == {"tasks_in_runs": 1, "tasks_total": 2}
    assert detail_b["membership_coverage"] == {"tasks_in_runs": 1, "tasks_total": 1}
    run_a = next(item for item in detail_a["batches"] if item["id"] == run_id)
    run_b = next(item for item in detail_b["batches"] if item["id"] == run_id)
    assert (run_a["selected_task_count"], run_a["dataset_task_count"]) == (1, 2)
    assert (run_b["selected_task_count"], run_b["dataset_task_count"]) == (1, 1)


def test_run_aliases_cover_grants_feedback_export_and_reconcile(hierarchy_client):
    admin = hierarchy_client["admin"]
    dataset, task = create_dataset(admin, "Alias dataset", "alias-task")
    created = admin.post("/api/runs", headers=ORIGIN, json={"name": "Run alias fixture",
        "dataset_ids": [dataset["id"]], "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    task_id = task["task_id"]

    viewer = TestClient(main.app)
    viewer_user = viewer.post("/api/auth/signup", headers=ORIGIN, json={"name": "Alias Viewer",
        "email": "alias-viewer@example.test", "password": "alias-viewer-password"}).json()
    grant = admin.post(f"/api/runs/{run_id}/grants", headers=ORIGIN,
        json={"user_id": viewer_user["id"], "role": "viewer"})
    assert grant.status_code == 200, grant.text
    assert viewer.get(f"/api/runs/{run_id}").status_code == 200
    revoked = admin.delete(f"/api/runs/{run_id}/grants/{grant.json()['id']}", headers=ORIGIN)
    assert revoked.status_code == 204
    assert viewer.get(f"/api/runs/{run_id}").status_code == 403

    reconciled = admin.post(f"/api/runs/{run_id}/reconcile", headers=ORIGIN)
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["reconciled"] is False and reconciled.json()["status"] == "draft"

    feedback = admin.post(f"/api/runs/{run_id}/tasks/{task_id}/feedback", headers=ORIGIN,
        json={"text": "Run alias feedback check.", "step_id": "step-1"})
    assert feedback.status_code == 200, feedback.text
    feedback_list = admin.get(f"/api/runs/{run_id}/tasks/{task_id}/feedback")
    assert feedback_list.status_code == 200
    assert feedback_list.json()["total"] == 1
    assert feedback_list.json()["items"][0]["id"] == feedback.json()["id"]
    exported = admin.get(f"/api/runs/{run_id}/tasks/{task_id}/export?format=json")
    assert exported.status_code == 200 and exported.json()["task_id"] == task_id

    assert admin.post(f"/api/runs/{run_id}/archive", headers=ORIGIN).json()["archived"] is True
    assert admin.post(f"/api/tasks/{task['task_definition_id']}/archive", headers=ORIGIN).json()["archived"] is True
    assert admin.post(f"/api/datasets/{dataset['id']}/archive", headers=ORIGIN).json()["archived"] is True


def test_direct_run_grant_exposes_only_authorized_run_members_to_analytics(hierarchy_client):
    admin = hierarchy_client["admin"]
    dataset_a, task_a = create_dataset(admin, "Direct grant A", "direct-grant-a")
    dataset_b, task_b = create_dataset(admin, "Direct grant B", "direct-grant-b")
    created = admin.post("/api/runs", headers=ORIGIN, json={"name": "Directly shared run",
        "task_definition_ids": [task_a["task_definition_id"], task_b["task_definition_id"]],
        "execution": {"backend": "saved_replay", "budget_usd": 0}})
    assert created.status_code == 200, created.text
    run = created.json()

    viewer = TestClient(main.app)
    viewer_user = viewer.post("/api/auth/signup", headers=ORIGIN, json={"name": "Direct Grant Viewer",
        "email": "direct-grant-viewer@example.test", "password": "direct-grant-viewer-password"}).json()
    grant = admin.post(f"/api/runs/{run['id']}/grants", headers=ORIGIN,
        json={"user_id": viewer_user["id"], "role": "viewer"})
    assert grant.status_code == 200, grant.text
    assert viewer.get(f"/api/datasets/{dataset_a['id']}").status_code == 403

    run_detail = viewer.get(f"/api/runs/{run['id']}")
    assert run_detail.status_code == 200, run_detail.text
    source_rows = {item["id"]: item for item in run_detail.json()["source_datasets"]}
    for dataset_id in (dataset_a["id"], dataset_b["id"]):
        assert source_rows[dataset_id]["partial_access"] is True
        assert source_rows[dataset_id]["task_count"] == 1
        assert "total_task_count" not in source_rows[dataset_id]

    catalog = viewer.get("/api/catalog").json()
    catalog_run = next(item for item in catalog["runs"] if item["id"] == run["id"])
    assert catalog_run["partial_access"] is True
    assert catalog_run["task_count"] == 2
    assert catalog_run["dataset_ids"] == []
    assert all(task["task_definition_id"] not in {
        task_a["task_definition_id"], task_b["task_definition_id"]} for task in catalog["tasks"])

    analytics = viewer.post("/api/analytics/query", headers=ORIGIN, json={"run_ids": [run["id"]]})
    assert analytics.status_code == 200, analytics.text
    report = analytics.json()
    assert report["counts"]["task_definitions"] == 2
    assert report["counts"]["selected_task_definitions"] == 2
    assert report["counts"]["run_members"] == 2
    assert {row["task_definition_id"] for row in report["rows"]} == {
        task_a["task_definition_id"], task_b["task_definition_id"]}
    hidden_dataset_query = viewer.post("/api/analytics/query", headers=ORIGIN,
        json={"dataset_ids": [dataset_a["id"]], "run_ids": [run["id"]]})
    assert hidden_dataset_query.status_code == 404

    revoked = admin.delete(f"/api/runs/{run['id']}/grants/{grant.json()['id']}", headers=ORIGIN)
    assert revoked.status_code == 204
    assert viewer.get(f"/api/runs/{run['id']}").status_code == 403
    assert all(item["id"] != run["id"] for item in viewer.get("/api/catalog").json()["runs"])
    assert viewer.post("/api/analytics/query", headers=ORIGIN,
        json={"run_ids": [run["id"]]}).status_code == 404
