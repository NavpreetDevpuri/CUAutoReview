#!/usr/bin/env python3
"""Import bundled demo tasks without inference or replacing existing records/access."""

from __future__ import annotations

import argparse
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from seed_demo import LOCAL, MANIFEST, ROOT, Client, private_write, seed_origin

BASE = os.environ.get("CUAUTOREVIEW_URL", "http://127.0.0.1:8000")
REPORT = LOCAL / "demo-import-report.json"
FIXTURE_PREFIXES = ("Acceptance ", "Acceptance ZIP ", "Unknown outcome check ", "Batch completion check ")
RUN_PREFIXES = (
    "Acceptance ",
    "Acceptance replay ",
    "Fixed acceptance ",
    "Unknown outcome waits ",
    "Batch completion saved replay ",
)


def missing_task_zip(path: Path, missing: set[str]) -> bytes:
    """Include only missing bundled tasks, preserving any edited existing revisions."""
    output = io.BytesIO()
    with ZipFile(path) as source, ZipFile(output, "w", ZIP_DEFLATED) as archive:
        manifest = json.loads(source.read("dataset.json"))
        manifest["tasks"] = [task for task in manifest["tasks"] if task["task_id"] in missing]
        if {task["task_id"] for task in manifest["tasks"]} != missing:
            raise RuntimeError("The bundled ZIP does not contain the expected missing tasks.")
        archive.writestr("dataset.json", json.dumps(manifest))
        assets = {
            step["screenshot"] for task in manifest["tasks"] for step in task.get("steps", []) if step.get("screenshot")
        }
        for name in sorted(assets):
            archive.writestr(name, source.read(name))
    return output.getvalue()


def seed_datasets(base=BASE, *, archive_old_fixtures=False):
    base = seed_origin(base)
    if not MANIFEST.is_file():
        raise RuntimeError("Demo accounts are missing. Run seed_workspace.py or seed_demo.py first.")
    accounts = json.loads(MANIFEST.read_text())
    account = next(person for person in accounts["accounts"] if person["key"] == "admin")
    client = Client(base)
    client.call("POST", "/auth/login", {key: account[key] for key in ("email", "password")})
    existing = client.items("/datasets?include_archived=true")
    source = json.loads((ROOT / "platform/demo-data/manifest.json").read_text())
    prior = json.loads(REPORT.read_text()) if REPORT.exists() else {}
    prior_ids = {item["slug"]: item["id"] for item in prior.get("datasets", [])}
    report = {"datasets": [], "archived_dataset_ids": [], "archived_run_ids": [], "new_inference_calls": 0}
    verified = set()
    for item in source["datasets"]:
        dataset = next((row for row in existing if row["id"] == prior_ids.get(item["slug"])), None)
        dataset = dataset or next((row for row in existing if row["name"] == item["name"]), None)
        created = dataset is None
        description = (
            f"Distinct public OSWorld tasks for {item['name'].lower()}. Pinned historical "
            "rollouts with source scores; human failure labels are not supplied."
        )
        if created:
            dataset = client.call("POST", "/datasets", {"name": item["name"], "description": description})
        detail = client.call("GET", f"/datasets/{dataset['id']}?include_archived=true")
        tasks = detail["tasks"]
        expected = set(item["task_ids"])
        missing = expected - {task["task_id"] for task in tasks}
        imported = {"created": 0, "revised": 0, "unchanged": len(expected - missing)}
        if missing:
            if dataset.get("archived"):
                raise RuntimeError(
                    f"Demo dataset {item['name']} is archived and lacks bundled tasks. "
                    "Restore it explicitly before reseeding."
                )
            if not created and dataset.get("description") != description:
                raise RuntimeError(
                    f"Dataset name {item['name']} is already in use. Its content and access were preserved."
                )
            request = urllib.request.Request(
                base + f"/api/datasets/{dataset['id']}/import-zip",
                data=missing_task_zip(ROOT / item["zip"], missing),
                method="POST",
                headers={"Content-Type": "application/zip", "Origin": base},
            )
            try:
                with client.opener.open(request, timeout=90) as response:
                    imported = json.load(response)
            except urllib.error.HTTPError as exc:
                raise RuntimeError(
                    f"Demo ZIP import failed with HTTP {exc.code}; existing records were retained."
                ) from None
            tasks = client.call("GET", f"/datasets/{dataset['id']}?include_archived=true")["tasks"]
        if created:
            client.call(
                "PUT",
                f"/datasets/{dataset['id']}/shares",
                {
                    "workspace_shared": True,
                    "users": [],
                    "teams": [
                        {"target_id": team["id"], "role": "reviewer" if team["name"] == "Demo Reviewers" else "viewer"}
                        for team in accounts["teams"]
                    ],
                },
            )
        # Existing shares, task revisions and archive state belong to the user.
        present = {task["task_id"] for task in tasks}
        if not expected <= present or verified & expected:
            raise RuntimeError("Bundled demo task membership is incomplete or duplicated.")
        verified.update(expected)
        report["datasets"].append(
            {
                **item,
                "id": dataset["id"],
                "archived": bool(dataset.get("archived")),
                "tasks": [
                    {
                        "task_id": task["task_id"],
                        "task_definition_id": task.get("task_definition_id") or task.get("definition_id") or task["id"],
                        "title": task.get("title"),
                    }
                    for task in tasks
                ],
                "import": {key: imported.get(key) for key in ("created", "revised", "unchanged")},
            }
        )
        private_write(REPORT, json.dumps(report, indent=2) + "\n")
        suffix = " (archived state preserved)" if dataset.get("archived") else ""
        print(f"{item['name']}: {len(expected)} bundled tasks ready{suffix}", flush=True)
    if archive_old_fixtures:
        for dataset in existing:
            if not dataset.get("archived") and (
                dataset["name"].startswith(FIXTURE_PREFIXES)
                or dataset["name"] in ("Saved POC examples", "Example ZIP walkthrough")
            ):
                client.call("POST", f"/datasets/{dataset['id']}/archive")
                report["archived_dataset_ids"].append(dataset["id"])
        for run in client.items("/runs?include_archived=true"):
            if (
                not run.get("archived")
                and (run["name"].startswith(RUN_PREFIXES) or run["name"] == "Retained POC replay")
                and run["status"] not in ("running", "queued")
            ):
                client.call("POST", f"/runs/{run['id']}/archive")
                report["archived_run_ids"].append(run["id"])
    if len(verified) != 8:
        raise RuntimeError("Expected eight distinct bundled task IDs.")
    report["verified_unique_task_count"] = len(verified)
    private_write(REPORT, json.dumps(report, indent=2) + "\n")
    print("Verified eight unique bundled tasks. No model jobs started.", flush=True)
    print(f"Import report: {REPORT}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE)
    parser.add_argument(
        "--archive-fixtures",
        "--archive-old-fixtures",
        dest="archive_old_fixtures",
        action="store_true",
        help="Explicitly soft-archive named old test fixtures; default preserves their visibility.",
    )
    args = parser.parse_args()
    try:
        seed_datasets(args.base_url, archive_old_fixtures=args.archive_old_fixtures)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Demo import stopped: {exc}\n")


if __name__ == "__main__":
    main()
