#!/usr/bin/env python3
"""Check real saved-replay batch completion and unknown-outcome status."""
from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
import time

from e2e_local import BASE, ROOT, Client


def main() -> None:
    account_path = ROOT / "platform/.local/test-account.json"
    if not account_path.is_file():
        raise RuntimeError("Missing ignored platform/.local/test-account.json bootstrap credentials")
    credentials = json.loads(account_path.read_text())

    admin = Client()
    identity = admin.call("POST", "/auth/login", {
        "email": credentials["email"], "password": credentials["password"]})
    if identity.get("role") != "admin":
        raise RuntimeError("The bootstrap account is not a workspace administrator")

    source = json.loads((ROOT / "poc/runs/latest/run.json").read_text())["tasks"]
    if len(source) != 5:
        raise RuntimeError(f"Expected the retained five-task example, found {len(source)} tasks")
    preset = next((item for item in admin.call("GET", "/presets")["items"]
                   if item.get("backend") == "saved_replay"), None)
    if not preset:
        raise RuntimeError("No saved_replay preset is available")

    suffix = str(time.time_ns())[-10:]
    dataset = admin.call("POST", "/datasets", {
        "name": f"Batch completion check {suffix}",
        "description": "Labeled real-service check using the five retained POC tasks. Saved replay only."})
    imported = admin.call("POST", f"/datasets/{dataset['id']}/import", {
        "format": "cuautoreview", "tasks": source})
    if imported.get("created") != 5:
        raise AssertionError(f"Expected five imported retained tasks, got {imported}")
    batch = admin.call("POST", "/batches", {
        "name": f"Batch completion saved replay {suffix}",
        "description": "Acceptance check for terminal batch status. No model calls.",
        "dataset_id": dataset["id"], "preset_id": preset["id"], "mode": "fixed"})
    batch_id = batch["id"]

    started = admin.call("POST", f"/batches/{batch_id}/start", {})
    if started.get("jobs_added") != 5:
        raise AssertionError(f"Expected five review jobs, got {started}")
    deadline = time.monotonic() + 90
    jobs = []
    while time.monotonic() < deadline:
        jobs = [job for job in admin.call("GET", "/jobs?per_page=500")["items"]
                if job.get("batch_id") == batch_id]
        if len(jobs) == 5 and all(job.get("status") == "completed" for job in jobs):
            break
        failures = [job for job in jobs if job.get("status") in ("failed", "cancelled")]
        if failures:
            raise AssertionError(f"Saved replay jobs did not complete: {failures}")
        time.sleep(0.5)
    if len(jobs) != 5 or not all(job.get("status") == "completed" for job in jobs):
        raise TimeoutError(f"Five saved-replay jobs did not finish within 90 seconds: {jobs}")
    if any(job.get("cost_usd") != 0 or (job.get("usage") or {}).get("kind") != "saved_replay"
           for job in jobs):
        raise AssertionError("The acceptance batch did not remain zero-cost saved replay")

    # Check the stored status directly after the last job commits. This must not
    # be repaired by restarting the batch or invoking the reconciliation route.
    finished = admin.call("GET", f"/batches/{batch_id}")
    progress = finished.get("progress") or {}
    if finished.get("status") != "completed" or progress.get("completed") != 5 or progress.get("total") != 5:
        raise AssertionError(f"Batch did not persist completed after its final job: {finished}")
    reconcile = admin.call("POST", f"/batches/{batch_id}/reconcile", {})
    if reconcile.get("reconciled") is not False or reconcile.get("status") != "completed":
        raise AssertionError(f"Reconcile should be a no-op for an already completed batch: {reconcile}")

    unknown_task = copy.deepcopy(source[0])
    unknown_task["task_id"] = f"unknown-outcome-{suffix}"
    unknown_task["outcome"] = "unknown"
    unknown_dataset = admin.call("POST", "/datasets", {
        "name": f"Unknown outcome check {suffix}",
        "description": "One retained task with unknown outcome; it must wait for review."})
    unknown_import = admin.call("POST", f"/datasets/{unknown_dataset['id']}/import", {
        "format": "cuautoreview", "tasks": [unknown_task]})
    if unknown_import.get("created") != 1:
        raise AssertionError(f"Unknown-outcome fixture was not imported: {unknown_import}")
    unknown_batch = admin.call("POST", "/batches", {
        "name": f"Unknown outcome waits {suffix}",
        "description": "Acceptance check: unknown outcomes are never dispatched.",
        "dataset_id": unknown_dataset["id"], "preset_id": preset["id"], "mode": "fixed"})
    unknown_started = admin.call("POST", f"/batches/{unknown_batch['id']}/start", {})
    if unknown_started.get("jobs_added") != 0 or unknown_started.get("status") != "awaiting_review":
        raise AssertionError(f"Unknown outcome must remain unresolved without dispatch: {unknown_started}")
    unknown_final = admin.call("GET", f"/batches/{unknown_batch['id']}")
    unknown_progress = unknown_final.get("progress") or {}
    if (unknown_final.get("status") != "awaiting_review" or
            unknown_progress.get("awaiting_review") != 1 or unknown_progress.get("completed") != 0):
        raise AssertionError(f"Unknown outcome was reported as completed: {unknown_final}")
    unknown_reconcile = admin.call("POST", f"/batches/{unknown_batch['id']}/reconcile", {})
    if (unknown_reconcile.get("reconciled") is not False or
            unknown_reconcile.get("status") != "awaiting_review"):
        raise AssertionError(f"Reconcile must preserve the unresolved outcome: {unknown_reconcile}")

    result = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_url": BASE,
        "provider_calls": 0,
        "checks": [
            {"check": "Five retained tasks complete with persisted batch status completed", "status": "passed"},
            {"check": "Explicit reconcile is a no-op for an already completed batch", "status": "passed"},
            {"check": "Unknown outcome remains awaiting_review with zero jobs", "status": "passed"},
            {"check": "Explicit reconcile preserves unresolved unknown outcome", "status": "passed"},
        ],
        "batch_id": batch_id,
        "task_count": len(jobs),
        "unknown_batch_id": unknown_batch["id"],
        "unknown_jobs_added": unknown_started["jobs_added"],
        "note": "Real-service saved-replay status checks, not model quality, scale, or production certification.",
    }
    output = ROOT / "platform/batch-completion-verification.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Saved {output.relative_to(ROOT)}")
    for item in result["checks"]:
        print(f"PASS {item['check']}")


if __name__ == "__main__":
    main()
