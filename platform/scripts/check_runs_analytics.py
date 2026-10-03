#!/usr/bin/env python3
"""Check run hierarchy, analytics, shares, archive and replay compare on local services.

This script uses the existing ignored local admin credentials and saved replay only.
It never enables a live model backend. All created runs, task definitions and datasets
are soft-archived in the final cleanup block.
"""
from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
import secrets
import time

from e2e_local import BASE, ROOT, Client


RESULTS: list[dict[str, str]] = []
FIXTURE_PREFIX = "Acceptance hierarchy"
POLL_SECONDS = 90


def passed(label: str) -> None:
    RESULTS.append({"check": label, "status": "passed"})
    print("PASS " + label, flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_client() -> tuple[Client, dict]:
    credentials_path = ROOT / "platform/.local/test-account.json"
    if not credentials_path.is_file():
        raise RuntimeError("Missing ignored platform/.local/test-account.json admin credentials")
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    client = Client()
    identity = client.call("POST", "/auth/login", {
        "email": credentials["email"], "password": credentials["password"]})
    require(identity.get("role") == "admin", "The configured local test account must be an administrator")
    return client, identity


def load_viewer() -> tuple[Client, dict, bool]:
    """Use an existing ignored demo viewer; create and later deactivate only as fallback."""
    account_path = ROOT / "platform/.local/demo-accounts.json"
    if account_path.is_file():
        accounts = json.loads(account_path.read_text(encoding="utf-8")).get("accounts", [])
        account = next((row for row in accounts if row.get("key") == "viewer"), None)
        if account:
            client = Client()
            try:
                identity = client.call("POST", "/auth/login", {
                    "email": account["email"], "password": account["password"]})
                if identity.get("role") == "viewer":
                    return client, identity, False
            except (AssertionError, KeyError):
                pass

    client = Client()
    suffix = str(time.time_ns())[-12:]
    identity = client.call("POST", "/auth/signup", {
        "name": f"{FIXTURE_PREFIX} temporary viewer {suffix}",
        "email": f"acceptance-hierarchy-viewer-{suffix}@example.test",
        "password": secrets.token_urlsafe(24)})
    require(identity.get("role") == "viewer", "Fallback acceptance user must be a viewer")
    return client, identity, True


def fixture_tasks() -> list[dict]:
    source_path = ROOT / "poc/runs/latest/run.json"
    if not source_path.is_file():
        raise RuntimeError("Missing retained saved diagnosis fixture at poc/runs/latest/run.json")
    rows = json.loads(source_path.read_text(encoding="utf-8")).get("tasks", [])
    diagnosed = [row for row in rows if isinstance(row.get("review"), dict)]
    if len(diagnosed) < 2:
        raise AssertionError("Expected at least two retained diagnosis tasks for replay comparison")
    return [copy.deepcopy(diagnosed[0]), copy.deepcopy(diagnosed[1])]


def create_fixture_dataset(admin: Client, name: str, task: dict, created: dict) -> tuple[dict, dict]:
    dataset = admin.call("POST", "/datasets", {
        "name": name, "description": f"{FIXTURE_PREFIX} saved-replay fixture. No live inference."})
    created["datasets"].append(dataset["id"])
    imported = admin.call("POST", f"/datasets/{dataset['id']}/import", {
        "format": "cuautoreview", "tasks": [task]})
    require(imported.get("created") == 1, f"Expected one saved diagnosis task in {name}: {imported}")
    detail = admin.call("GET", f"/datasets/{dataset['id']}")
    require(len(detail.get("tasks", [])) == 1, f"Expected one task definition in {name}")
    return dataset, detail["tasks"][0]


def run_tasks(admin: Client, run_id: str) -> list[dict]:
    return admin.call("GET", f"/runs/{run_id}/tasks?per_page=500").get("items", [])


def run_results(admin: Client, run_id: str) -> dict[str, dict]:
    output = {}
    for task in run_tasks(admin, run_id):
        history = task.get("review_history") or []
        if history:
            output[task["task_id"]] = history[-1]
    return output


def start_and_wait(admin: Client, run_id: str, expected_jobs: int) -> list[dict]:
    started = admin.call("POST", f"/runs/{run_id}/start", {})
    require(started.get("jobs_added") == expected_jobs,
            f"Expected {expected_jobs} saved-replay jobs, got {started}")
    deadline = time.monotonic() + POLL_SECONDS
    jobs: list[dict] = []
    while time.monotonic() < deadline:
        jobs = [row for row in admin.call("GET", "/jobs?per_page=500").get("items", [])
                if row.get("batch_id") == run_id]
        if len(jobs) == expected_jobs and all(row.get("status") == "completed" for row in jobs):
            return jobs
        failures = [row for row in jobs if row.get("status") in ("failed", "cancelled")]
        if failures:
            raise AssertionError(f"Saved-replay jobs did not complete: {failures}")
        time.sleep(0.5)
    raise TimeoutError(f"Saved-replay jobs did not complete within {POLL_SECONDS} seconds: {jobs}")


def best_effort_cleanup(admin: Client, created: dict, temporary_viewer_id: str | None) -> list[str]:
    errors: list[str] = []
    for run_id in reversed(created["runs"]):
        try:
            run = admin.call("GET", f"/runs/{run_id}?include_archived=true")
            if run.get("status") not in ("completed", "failed", "cancelled"):
                try:
                    admin.call("POST", f"/runs/{run_id}/cancel")
                except AssertionError:
                    pass
            if not run.get("archived"):
                admin.call("POST", f"/runs/{run_id}/archive")
        except Exception as exc:  # Cleanup continues so other test fixtures are still archived.
            errors.append(f"run {run_id}: {type(exc).__name__}: {exc}")
    for task_id in reversed(created["tasks"]):
        try:
            admin.call("POST", f"/tasks/{task_id}/archive")
        except Exception as exc:
            errors.append(f"task {task_id}: {type(exc).__name__}: {exc}")
    for dataset_id in reversed(created["datasets"]):
        try:
            dataset = admin.call("GET", f"/datasets/{dataset_id}?include_archived=true")
            # Shares belong only to these test-created datasets. Remove viewer access before archive.
            admin.call("PUT", f"/datasets/{dataset_id}/shares", {
                "workspace_shared": False, "users": [], "teams": []})
            if not dataset.get("archived"):
                admin.call("POST", f"/datasets/{dataset_id}/archive")
        except Exception as exc:
            errors.append(f"dataset {dataset_id}: {type(exc).__name__}: {exc}")
    if temporary_viewer_id:
        try:
            admin.call("PATCH", f"/users/{temporary_viewer_id}", {"active": False})
        except Exception as exc:
            errors.append(f"temporary viewer {temporary_viewer_id}: {type(exc).__name__}: {exc}")
    return errors


def main() -> None:
    admin, admin_identity = load_client()
    viewer, viewer_identity, created_viewer = load_viewer()
    source_a, source_b = fixture_tasks()
    suffix = str(time.time_ns())[-12:]
    created: dict[str, list[str]] = {"datasets": [], "tasks": [], "runs": []}
    viewer_id_to_deactivate = viewer_identity["id"] if created_viewer else None
    assertions: dict[str, object] = {}

    try:
        dataset_a, task_a = create_fixture_dataset(
            admin, f"{FIXTURE_PREFIX} source A {suffix}", source_a, created)
        dataset_b, task_b = create_fixture_dataset(
            admin, f"{FIXTURE_PREFIX} source B {suffix}", source_b, created)
        task_a_id = task_a["task_definition_id"]
        task_b_id = task_b["task_definition_id"]
        created["tasks"].extend([task_a_id, task_b_id])
        task_a_revision = task_a["revision_id"]
        task_b_revision = task_b["revision_id"]

        configured = admin.call("POST", "/runs", {
            "name": f"{FIXTURE_PREFIX} explicit multi-source draft {suffix}",
            "description": "Two source datasets and explicitly selected task definitions.",
            "task_definition_ids": [task_a_id, task_b_id],
            "workflow_revision_id": "trajectory_review@1",
            "execution": {"backend": "saved_replay", "reasoning": "none", "budget_usd": 0},
        })
        created["runs"].append(configured["id"])
        require(configured["status"] == "draft", "New run did not start in draft status")
        require(set(configured.get("dataset_ids", [])) == {dataset_a["id"], dataset_b["id"]},
                "Explicit task selection did not produce a two-dataset run")
        per_source_counts = {item["id"]: (item.get("task_count"), item.get("total_task_count"))
            for item in configured.get("source_datasets", [])}
        require(per_source_counts == {dataset_a["id"]: (1, 1), dataset_b["id"]: (1, 1)},
                f"Run source dataset counts are incorrect: {per_source_counts}")
        require(configured.get("progress", {}).get("total") == 2,
                "Explicit two-task run has an unexpected member count")
        original_items = run_tasks(admin, configured["id"])
        original_revisions = {item["task_id"]: item["revision_id"] for item in original_items}
        require(original_revisions == {source_a["task_id"]: task_a_revision,
                                       source_b["task_id"]: task_b_revision},
                f"Run did not pin the expected task revisions: {original_revisions}")
        configured = admin.call("POST", f"/runs/{configured['id']}/configure", {
            "workflow_revision_id": "trajectory_review@1",
            "execution": {"backend": "saved_replay", "reasoning": "none", "budget_usd": 0,
                          "configuration": {"timeout_seconds": 45, "max_output_tokens": 1024,
                                            "max_images": 0}},
        })
        require(configured.get("configuration", {}).get("revision") == 2,
                "Draft configure did not advance the pinned configuration revision")
        original_snapshot = copy.deepcopy(configured["configuration"])
        require(original_snapshot["workflow_snapshot"]["revision_id"] == "trajectory_review@1",
                "Draft configuration did not pin its workflow")
        passed("Explicit two-dataset task selection and draft workflow/execution configure")

        cancelled = admin.call("POST", f"/runs/{configured['id']}/cancel")
        require(cancelled.get("status") == "cancelled", "Draft run could not be cancelled")
        successor = admin.call("POST", f"/runs/{configured['id']}/rerun", {})
        created["runs"].append(successor["id"])
        require(successor["id"] != configured["id"] and successor.get("status") == "draft",
                "Rerun did not create a new draft run")
        require(successor.get("configuration", {}).get("rerun_of_run_id") == configured["id"],
                "Rerun source link was not retained")
        require(successor["configuration"]["workflow_snapshot"] == original_snapshot["workflow_snapshot"],
                "Rerun changed the pinned workflow snapshot")
        require(successor["configuration"]["execution_snapshot"] == original_snapshot["execution_snapshot"],
                "Rerun changed the pinned execution snapshot")
        require({item["task_id"]: item["revision_id"] for item in run_tasks(admin, successor["id"])} == original_revisions,
                "Rerun did not preserve frozen task revisions")
        require(admin.call("GET", f"/runs/{configured['id']}")["status"] == "cancelled",
                "Source run history did not remain intact after rerun")
        passed("Draft cancel and new rerun successor preserve source history and frozen snapshots")

        # A saved replay of the retained diagnosis fixture exercises the real job path without model calls.
        replay_jobs = start_and_wait(admin, successor["id"], expected_jobs=2)
        require(all((job.get("usage") or {}).get("kind") == "saved_replay" and job.get("cost_usd") == 0
                    for job in replay_jobs), "Replay job usage was not zero-cost saved replay")
        successor = admin.call("GET", f"/runs/{successor['id']}")
        require(successor.get("status") == "completed", f"Saved replay did not complete: {successor}")
        successor_config = successor["configuration"]
        require(successor_config["workflow_snapshot"] == original_snapshot["workflow_snapshot"] and
                successor_config["execution_snapshot"] == original_snapshot["execution_snapshot"],
                "Starting a rerun changed its frozen snapshots")
        admin.call("POST", f"/runs/{successor['id']}/configure", {
            "execution": {"backend": "saved_replay", "budget_usd": 0}}, expected=409)
        passed("Saved replay completes with no provider calls and freezes successor configuration")

        second_successor = admin.call("POST", f"/runs/{successor['id']}/rerun", {})
        created["runs"].append(second_successor["id"])
        require(second_successor["configuration"]["execution_snapshot"] == original_snapshot["execution_snapshot"],
                "Successor rerun lost its execution snapshot")
        require({item["task_id"]: item["revision_id"] for item in run_tasks(admin, second_successor["id"])} == original_revisions,
                "Successor rerun changed task revisions")
        second_jobs = start_and_wait(admin, second_successor["id"], expected_jobs=2)
        require(all((job.get("usage") or {}).get("kind") == "saved_replay" and job.get("cost_usd") == 0
                    for job in second_jobs), "Successor rerun dispatched a non-replay job")
        second_results = run_results(admin, second_successor["id"])
        first_results = run_results(admin, successor["id"])
        task_key = source_a["task_id"]
        result_ids = [first_results[task_key]["id"], second_results[task_key]["id"]]
        compare = admin.call("POST", "/analytics/compare", {"result_ids": result_ids})
        require(compare.get("aligned", {}).get("task_id") == task_key,
                "Comparison omitted the aligned task_id")
        require(compare.get("aligned", {}).get("task_revision_id") == task_a_revision,
                "Comparison did not align the frozen task revision")
        for result in compare.get("results", []):
            require(result.get("task_id") == task_key and result.get("backend") == "saved_replay" and
                    result.get("model") == "retained-poc" and isinstance(result.get("review"), dict),
                    f"Compare result omitted replay metadata or full review: {result}")
        require(compare.get("verdict") is None, "Comparison must not invent a verdict")
        passed("Same-revision saved replay comparison includes task identity, backend, model and full reviews")

        # Task history contains original cancellation and both saved-replay successors.
        history = admin.call("GET", f"/datasets/{dataset_a['id']}/tasks/{task_a_id}")
        history_run_ids = {row["run_id"] for row in history.get("runs", [])}
        require({configured["id"], successor["id"], second_successor["id"]} <= history_run_ids,
                "Task history omitted the source or a rerun successor")
        require(sum(len(row.get("reviews", [])) for row in history.get("runs", [])) >= 2,
                "Task history did not preserve replay reviews")
        passed("Task history preserves source run, successors and saved replay reviews")

        query = admin.call("POST", "/analytics/query", {
            "dataset_ids": [dataset_a["id"], dataset_b["id"]],
            "run_ids": [successor["id"]], "task_definition_ids": [task_a_id, task_b_id]})
        require(query.get("counts", {}).get("task_definitions") == 2 and
                query.get("counts", {}).get("selected_task_definitions") == 2 and
                query.get("counts", {}).get("run_members") == 2,
                f"Multi-source analytics selection did not return two matched tasks: {query}")
        run_b_only = admin.call("POST", "/runs", {
            "name": f"{FIXTURE_PREFIX} B-only filter run {suffix}",
            "dataset_ids": [dataset_b["id"]],
            "execution": {"backend": "saved_replay", "reasoning": "none", "budget_usd": 0}})
        created["runs"].append(run_b_only["id"])
        empty = admin.call("POST", "/analytics/query", {
            "dataset_ids": [dataset_a["id"]], "run_ids": [run_b_only["id"]],
            "task_definition_ids": [task_a_id]})
        require(empty.get("counts", {}).get("task_definitions") == 0 and
                empty.get("counts", {}).get("selected_task_definitions") == 1 and
                empty.get("counts", {}).get("run_members") == 0 and empty.get("rows") == [],
                f"AND analytics filters should produce an empty intersection: {empty}")
        partial = admin.call("POST", "/analytics/query", {
            "dataset_ids": [dataset_a["id"], dataset_b["id"]], "run_ids": [successor["id"]],
            "task_definition_ids": [task_a_id, task_b_id]})
        require(partial.get("counts", {}).get("task_definitions") == 2,
                "Matched-task count changed after including both selected sources")
        passed("Analytics dimensions intersect, with matched and pre-intersection task counts")

        admin.call("PUT", f"/datasets/{dataset_a['id']}/shares", {
            "workspace_shared": False, "users": [{"target_id": viewer_identity["id"], "role": "viewer"}]})
        admin.call("PUT", f"/datasets/{dataset_b['id']}/shares", {
            "workspace_shared": False, "users": [{"target_id": viewer_identity["id"], "role": "viewer"}]})
        require(viewer.call("GET", f"/datasets/{dataset_a['id']}").get("id") == dataset_a["id"],
                "Shared viewer cannot access dataset A")
        require(viewer.call("GET", f"/datasets/{dataset_b['id']}").get("id") == dataset_b["id"],
                "Shared viewer cannot access dataset B")
        require(viewer.call("GET", f"/runs/{successor['id']}").get("id") == successor["id"],
                "Viewer shared on all source datasets cannot access the run")
        viewer.call("POST", "/analytics/compare", {"result_ids": result_ids})
        admin.call("PUT", f"/datasets/{dataset_b['id']}/shares", {
            "workspace_shared": False, "users": [], "teams": []})
        viewer.call("GET", f"/datasets/{dataset_b['id']}", expected=403)
        viewer.call("GET", f"/runs/{successor['id']}", expected=403)
        viewer.call("POST", "/analytics/compare", {"result_ids": result_ids}, expected=403)
        admin.call("PUT", f"/datasets/{dataset_a['id']}/shares", {
            "workspace_shared": False, "users": [], "teams": []})
        viewer.call("GET", f"/datasets/{dataset_a['id']}", expected=403)
        passed("Dataset sharing grants multi-source visibility only while all source grants remain")

        assertions = {
            "dataset_ids": [dataset_a["id"], dataset_b["id"]],
            "task_definition_ids": [task_a_id, task_b_id],
            "source_run_id": configured["id"],
            "successor_run_id": successor["id"],
            "second_successor_run_id": second_successor["id"],
            "source_task_revision_ids": original_revisions,
            "saved_replay_job_ids": [job["id"] for job in replay_jobs + second_jobs],
            "compared_review_result_ids": result_ids,
            "viewer_id": viewer_identity["id"],
        }
    finally:
        cleanup_errors = best_effort_cleanup(admin, created, viewer_id_to_deactivate)

    require(not cleanup_errors, "Could not soft-archive all acceptance fixtures: " + "; ".join(cleanup_errors))
    result = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_url": BASE,
        "admin_user_id": admin_identity["id"],
        "provider_calls": 0,
        "checks": RESULTS,
        "fixtures": assertions,
        "soft_archived": {"run_ids": created["runs"], "task_definition_ids": created["tasks"],
                          "dataset_ids": created["datasets"]},
        "note": "Local saved-replay hierarchy and analytics checks. No live model calls or production certification.",
    }
    output = ROOT / "platform/evidence/runs-analytics-verification.json"
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output.relative_to(ROOT)}")
    print("PASS Soft-archived all created runs, task definitions and datasets")


if __name__ == "__main__":
    main()
