#!/usr/bin/env python3
"""Read-only Docker quick-start checks; only login sessions and a local baseline are written.

Run in the isolated seed container after seeding, repeat after the second seed.
No analysis, model, job, dataset, or identity mutation endpoints are invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

EXPECTED_ROLES = {
    "admin": "admin",
    "manager": "manager",
    "reviewer": "reviewer",
    "reviewer2": "reviewer",
    "viewer": "viewer",
}
EXPECTED_TEAMS = {
    "Demo Coordinators": {"manager"},
    "Demo Reviewers": {"reviewer", "reviewer2"},
    "Demo Observers": {"viewer"},
}
EXPECTED_DATASETS = {"Office documents": 3, "Web browsing": 3, "Image editing": 2}
MAX_BODY = 16 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def raw(self, method, path, body=None):
        require(path.startswith("/api/") and not path.startswith("//"), "API path must be relative")
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Origin": self.base},
        )
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            payload = response.read(MAX_BODY + 1)
            require(len(payload) <= MAX_BODY, "API response exceeded the verification limit")
            return response.status, response.headers.get("Content-Type", ""), payload

    def api(self, method, path, body=None):
        status, content_type, payload = self.raw(method, "/api" + path, body)
        require(status == 200, f"API check failed with HTTP {status}: {method} {path}")
        require("json" in content_type, "Expected a JSON API response")
        return json.loads(payload)

    def items(self, path):
        items, page = [], 1
        while True:
            separator = "&" if "?" in path else "?"
            result = self.api("GET", f"{path}{separator}page={page}&per_page=200")
            items.extend(result["items"])
            if len(items) >= result["total"] or not result["items"]:
                return items
            page += 1
            require(page <= 20, "Verification pagination limit reached")


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".quickstart-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(value, output, indent=2, sort_keys=True)
            output.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def image_check(client, path):
    require(
        isinstance(path, str) and path.startswith("/api/artifacts/"),
        "Screenshot must use an authorized API artifact link",
    )
    status, mime, data = client.raw("GET", path)
    require(status == 200, f"Screenshot GET failed with HTTP {status}")
    require(
        mime.split(";")[0] in ("image/png", "image/jpeg", "image/webp"),
        "Screenshot response did not declare an allowed image type",
    )
    require(
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or (data.startswith(b"RIFF") and data[8:12] == b"WEBP"),
        "Screenshot response did not contain image bytes",
    )
    return len(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("CUAUTOREVIEW_URL", "http://app:8000"))
    parser.add_argument(
        "--local-dir", type=Path, default=Path(os.getenv("CUAUTOREVIEW_LOCAL_DIR", "/workspace/platform/.local"))
    )
    parser.add_argument(
        "--allow-saved-replay",
        action="store_true",
        help="Allow completed zero-cost saved-replay jobs, but no provider-backed jobs",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    parsed = urlsplit(base)
    require(
        parsed.scheme == "http"
        and parsed.hostname in ("app", "localhost", "127.0.0.1", "::1")
        and not any((parsed.username, parsed.password, parsed.path, parsed.query, parsed.fragment)),
        "Verification is restricted to the local app service or loopback origin",
    )
    accounts_path = args.local_dir / "demo-accounts.json"
    state_path = args.local_dir / "docker-quickstart-verification-state.json"
    manifest = json.loads(accounts_path.read_text())
    people = {person["key"]: person for person in manifest["accounts"]}
    require(set(people) == set(EXPECTED_ROLES), "Expected exactly five demo account records")
    clients, identities = {}, {}
    for key, role in EXPECTED_ROLES.items():
        person = people[key]
        client = Client(base)
        identity = client.api("POST", "/auth/login", {k: person[k] for k in ("email", "password")})
        require(
            identity.get("role") == role and identity.get("active") is True,
            f"Demo {key} login did not have the expected active role",
        )
        require(identity.get("id") == person.get("id"), f"Demo {key} identity differs from the manifest")
        require(client.api("GET", "/auth/me")["id"] == identity["id"], "Session identity check failed")
        clients[key], identities[key] = client, identity["id"]
    admin = clients["admin"]
    health = admin.api("GET", "/health")
    require(
        health.get("status") == "ok" and health.get("object_store") == "s3",
        "Expected a healthy API using the S3-compatible object store",
    )
    users = admin.items("/users")
    require(
        len(users) == 5 and {row["id"] for row in users} == set(identities.values()),
        "Fresh workspace does not contain exactly five expected users",
    )
    teams = admin.items("/teams")
    require(
        len(teams) == 3 and {row["name"] for row in teams} == set(EXPECTED_TEAMS), "Expected exactly three demo teams"
    )
    team_state = {}
    for team in teams:
        require(
            {row["id"] for row in team["members"]} == {identities[key] for key in EXPECTED_TEAMS[team["name"]]},
            "Demo team membership differs from the expected seed",
        )
        team_state[team["name"]] = {"id": team["id"], "members": sorted(row["id"] for row in team["members"])}
    datasets = admin.items("/datasets")
    selected = [row for row in datasets if row["name"] in EXPECTED_DATASETS]
    require(len(selected) == 3, "Expected the three named distinct-task demo datasets")
    task_ids, task_state, screenshot_urls = [], {}, []
    for dataset in selected:
        detail = admin.api("GET", f"/datasets/{dataset['id']}")
        tasks = detail["tasks"]
        require(len(tasks) == EXPECTED_DATASETS[dataset["name"]], "Demo dataset task count differs from 3/3/2")
        task_state[dataset["name"]] = {"id": dataset["id"], "tasks": []}
        for task in tasks:
            task_ids.append(task["task_id"])
            task_state[dataset["name"]]["tasks"].append(
                {
                    "task_id": task["task_id"],
                    "definition_id": task["task_definition_id"],
                    "revision_id": task["revision_id"],
                    "revision": task.get("revision"),
                }
            )
            screenshots = [step["screenshot_url"] for step in task.get("steps", []) if step.get("screenshot_url")]
            require(bool(screenshots), "A demo task has no linked screenshot available for verification")
            image_check(admin, screenshots[0])
            screenshot_urls.append(screenshots[0])
        task_state[dataset["name"]]["tasks"].sort(key=lambda row: row["task_id"])
        viewer_detail = clients["viewer"].api("GET", f"/datasets/{dataset['id']}")
        require(len(viewer_detail["tasks"]) == len(tasks), "Viewer cannot read the shared dataset")
        image_check(
            clients["viewer"],
            next(
                step["screenshot_url"] for task in tasks for step in task.get("steps", []) if step.get("screenshot_url")
            ),
        )
    require(len(task_ids) == 8 and len(set(task_ids)) == 8, "Demo catalog does not contain eight distinct task IDs")
    status, _, _ = Client(base).raw("GET", screenshot_urls[0])
    require(status == 401, "An unauthenticated caller could access protected screenshot evidence")
    jobs = admin.items("/jobs")
    if args.allow_saved_replay:
        require(
            all(
                job.get("backend") == "saved_replay"
                and job.get("status") == "completed"
                and job.get("cost_usd") == 0
                and (job.get("usage") or {}).get("kind") == "saved_replay"
                for job in jobs
            ),
            "A job is not completed zero-cost saved replay",
        )
    else:
        require(not jobs, "Demo seeding unexpectedly created analysis jobs")
    fingerprint = hashlib.sha256(
        json.dumps(
            [[key, identities[key], people[key]["password"]] for key in sorted(people)], separators=(",", ":")
        ).encode()
    ).hexdigest()
    state = {
        "version": 1,
        "users": identities,
        "credential_fingerprint": fingerprint,
        "teams": team_state,
        "datasets": task_state,
    }
    repeated = state_path.exists()
    if repeated:
        require(
            json.loads(state_path.read_text()) == state,
            "Seed rerun changed user/team/task identities, passwords, or task revisions",
        )
    else:
        private_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "passed",
                "demo_logins_verified": 5,
                "roles_verified": 5,
                "teams_verified": 3,
                "distinct_demo_datasets": 3,
                "distinct_demo_tasks": 8,
                "other_preserved_datasets": len(datasets) - len(selected),
                "admin_screenshot_reads": len(screenshot_urls),
                "viewer_screenshot_reads": 3,
                "anonymous_screenshot_denied": True,
                "analysis_jobs": len(jobs),
                "provider_backed_jobs": 0,
                "verification_model_calls": 0,
                "repeat_seed_identity_password_revision_stability": "verified" if repeated else "baseline saved",
                "scope": (
                    "Seed, authentication, shared dataset access and retained screenshot storage; no queue "
                    "execution test"
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        # Never print response payloads, request bodies, cookies, or generated credentials.
        safe = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(json.dumps({"status": "failed", "reason": safe}))
        raise SystemExit(1) from None
