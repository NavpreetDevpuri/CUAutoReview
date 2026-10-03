#!/usr/bin/env python3
"""Replay the recorded 27 September 2026 visual-review experiment against the local platform.

This starts PAID hosted inference, so it does nothing without --run. The dataset and task
IDs below are specific to the workspace where the experiment was recorded; on another
workspace, edit them first. No provider keys are read by this script; workers must already
be enabled. Canary first, then remaining seven tasks, plus one optional matched comparison review.
Each job uses the platform's bounded retry policy; this script never restarts it.
"""

import argparse
import datetime as dt
import json
import time

from run_cli_comparison import ACCOUNT_FILE, REPORT_DIR, Api

DATASETS = [
    "99f788d5-a4fc-4b54-9cde-d15a4da9947e",
    "7878c36d-88c6-44b8-9114-894c6e86b948",
    "23af58f4-6d77-4e2f-9835-1fe3fe008915",
]
MATCHED = "06fe7178-4491-4589-810f-2e2bc9502122"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=["canary", "remaining", "codex"])
    parser.add_argument(
        "--run", action="store_true", help="Actually create and start the paid run; without it, only print the plan"
    )
    args = parser.parse_args()
    if not args.run:
        backend, model = ("codex", "gpt-6-sol") if args.scope == "codex" else ("gemini_cli", "gemini-3.8-flash")
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "scope": args.scope,
                    "backend": backend,
                    "model": model,
                    "datasets": DATASETS,
                    "matched_task_id": MATCHED,
                    "per_task_attempt_allowance_usd": 0.10,
                    "max_attempts_per_task": 4,
                    "note": "Hosted inference costs money. Re-run with --run to create and start this run.",
                },
                indent=2,
            )
        )
        return
    api = Api()
    account = json.loads(ACCOUNT_FILE.read_text())
    api.call("POST", "/auth/login", {"email": account["email"], "password": account["password"]})
    tasks = [
        task
        for dataset_id in DATASETS
        for task in api.call("GET", "/datasets/" + dataset_id)["tasks"]
        if (task["task_id"] != MATCHED if args.scope == "remaining" else task["task_id"] == MATCHED)
    ]
    backend, model = ("codex", "gpt-6-sol") if args.scope == "codex" else ("gemini_cli", "gemini-3.8-flash")
    config = {"timeout_seconds": 120, "max_output_tokens": 4096, "max_images": 32}
    if backend == "codex":
        config["codex_base_url"] = "https://us.api.openai.com/v1"
    execution = {"backend": backend, "model": model, "reasoning": "low", "budget_usd": 0.10, "configuration": config}
    suffix = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    if args.scope != "remaining":
        api.call("POST", "/presets", {"name": f"{model} screenshot review", **execution})
    run = api.call(
        "POST",
        "/runs",
        {
            "name": f"{model} visual review: {args.scope} {suffix}",
            "description": "New screenshot-enabled reviews. Historical text-only results are preserved. "
            "Up to three automatic retries for processing failures; benchmark outcomes stay unchanged.",
            "task_definition_ids": [task["task_definition_id"] for task in tasks],
            "workflow_revision_id": "trajectory_review@1",
            "execution": execution,
        },
    )
    run_id = run["id"]
    report = {
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "run_id": run_id,
        "scope": args.scope,
        "execution": execution,
        "planned_allowance": {
            "per_task_attempt_usd": 0.10,
            "max_attempts": 4,
            "total_usd": round(len(tasks) * 0.10 * 4, 2),
            "hard_billing_cap": False,
        },
        "tasks": [
            {
                "task_id": t["task_id"],
                "task_definition_id": t["task_definition_id"],
                "source_steps": len(t.get("steps", [])),
                "source_images": sum(bool(s.get("screenshot") or s.get("screenshot_path")) for s in t.get("steps", [])),
            }
            for t in tasks
        ],
    }
    target = REPORT_DIR / f"visual-review-{args.scope}-{suffix}.json"

    def save():
        target.write_text(json.dumps(report, indent=2) + "\n")

    save()
    api.call("POST", f"/runs/{run_id}/start", {"confirm_budget": True, "expected_budget_usd": 0.10})
    print(json.dumps({"run_id": run_id, "scope": args.scope, "tasks": len(tasks), "report": str(target)}), flush=True)
    deadline = time.monotonic() + 1500
    prior = None
    while time.monotonic() < deadline:
        jobs = [j for j in api.call("GET", "/jobs?per_page=500")["items"] if j["batch_id"] == run_id]
        report["jobs"] = jobs
        state = [(j["id"], j["status"], j["attempt_count"]) for j in jobs]
        if state != prior:
            print(
                json.dumps(
                    {
                        "jobs": [
                            {"status": j["status"], "attempts": j["attempt_count"], "error": j.get("error")}
                            for j in jobs
                        ]
                    }
                ),
                flush=True,
            )
            save()
            prior = state
        if len(jobs) == len(tasks) and all(j["status"] in ("completed", "failed", "cancelled") for j in jobs):
            break
        time.sleep(3)
    report["results"] = [api.call("GET", f"/runs/{run_id}/tasks/{t['task_id']}") for t in tasks]
    report["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
    save()
    print(
        json.dumps(
            {
                "report": str(target),
                "completed": sum(j["status"] == "completed" for j in report["jobs"]),
                "total": len(tasks),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
