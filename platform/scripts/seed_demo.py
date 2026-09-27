#!/usr/bin/env python3
"""Create local demo identities and grants through the API, without model calls."""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "platform/.local"
MANIFEST = LOCAL / "demo-accounts.json"
GUIDE = LOCAL / "demo-accounts.md"
PEOPLE = [
    ("admin", "Demo Admin", "admin"),
    ("manager", "Demo Manager", "manager"),
    ("reviewer", "Demo Reviewer", "reviewer"),
    ("reviewer2", "Demo Reviewer Two", "reviewer"),
    ("viewer", "Demo Viewer", "viewer"),
]
TEAMS = [
    ("Demo Coordinators", "manager", ["manager"], "Coordinate batches and review progress."),
    ("Demo Reviewers", "reviewer", ["reviewer", "reviewer2"], "Inspect evidence, leave feedback and propose labels."),
    ("Demo Observers", "viewer", ["viewer"], "Read trajectories and export recorded reviews."),
]


class Client:
    def __init__(self, base: str):
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + "/api" + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method, headers={"Content-Type": "application/json", "Origin": self.base})
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        raw = response.read()
        data = json.loads(raw) if raw and "json" in response.headers.get("Content-Type", "") else raw
        return response.status, data

    def call(self, method, path, body=None, expected=200):
        status, data = self.request(method, path, body)
        if status != expected:
            # Never echo submitted credentials or arbitrary response bodies.
            raise RuntimeError(f"{method} {path}: HTTP {status}, expected {expected}")
        return data

    def items(self, path):
        items, page = [], 1
        while True:
            result = self.call("GET", f"{path}?page={page}&per_page=200")
            items.extend(result["items"])
            if len(items) >= result["total"] or not result["items"]:
                return items
            page += 1


def private_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".seed-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_manifest(manifest):
    private_write(MANIFEST, json.dumps(manifest, indent=2) + "\n")


def provision_person(base, person):
    client = Client(base)
    status, user = client.request("POST", "/auth/login", {
        "email": person["email"], "password": person["password"]})
    if status == 200:
        if person.get("id") and person["id"] != user["id"]:
            raise RuntimeError(f"Account identity changed for {person['email']}; inspect the local manifest.")
        return user, client
    if status != 401:
        raise RuntimeError(f"Cannot check {person['email']}: HTTP {status}")
    status, user = client.request("POST", "/auth/signup", {
        key: person[key] for key in ("name", "email", "password")})
    if status == 409:
        raise RuntimeError(f"{person['email']} already exists with different credentials or is inactive. "
                           "No password, role or active status was changed.")
    if status != 200:
        raise RuntimeError(f"Cannot create {person['email']}: HTTP {status}")
    return user, client


def seed(base, admin_credentials=None):
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
        if manifest.get("base_url") != base or manifest.get("seed_version") != 1:
            raise RuntimeError("Existing demo manifest belongs to a different seed version or local URL.")
        expected = {name + "@cuautoreview.test" for name, _, _ in PEOPLE}
        if {p["email"] for p in manifest["accounts"]} != expected:
            raise RuntimeError("Demo account manifest has unexpected identities; no changes made.")
    else:
        manifest = {"seed_version": 1, "base_url": base, "accounts": [
            {"key": key, "name": name, "email": key + "@cuautoreview.test",
             "role": role, "password": secrets.token_urlsafe(18)}
            for key, name, role in PEOPLE]}
        # Persist passwords before the first API mutation, so interrupted runs can resume.
        save_manifest(manifest)

    admin = None
    credentials_path = admin_credentials or LOCAL / "test-account.json"
    if credentials_path.is_file():
        credentials = json.loads(credentials_path.read_text())
        admin = Client(base)
        identity = admin.call("POST", "/auth/login", {k: credentials[k] for k in ("email", "password")})
        if identity["role"] != "admin":
            raise RuntimeError("The supplied bootstrap account is not an administrator.")

    for person in manifest["accounts"]:
        user, client = provision_person(base, person)
        person["id"] = user["id"]
        save_manifest(manifest)
        if admin is None:
            if user["role"] != "admin":
                raise RuntimeError("This workspace already has an administrator. Rerun with "
                                   "--admin-credentials /path/to/admin.json containing email and password.")
            admin = client
        if not person.get("initialized"):
            if user["role"] != person["role"]:
                user = admin.call("PATCH", f"/users/{user['id']}", {"role": person["role"]})
            person["initialized"] = True
            save_manifest(manifest)
        elif user["role"] != person["role"]:
            raise RuntimeError(f"Role for {person['email']} was changed after seeding. It was preserved.")

    people = {p["key"]: p for p in manifest["accounts"]}
    existing_teams = {t["name"]: t for t in admin.items("/teams")}
    team_records = []
    for name, role, members, purpose in TEAMS:
        team = existing_teams.get(name)
        if not team:
            team = admin.call("POST", "/teams", {"name": name, "description": "Local demo: " + purpose})
        known_members = {m["id"] for m in team.get("members", [])}
        for key in members:
            if people[key]["id"] not in known_members:
                admin.call("POST", f"/teams/{team['id']}/members", {"user_id": people[key]["id"]})
        team_records.append({"id": team["id"], "name": name, "role": role, "members": members})
    manifest["teams"] = team_records

    batch = next((b for b in admin.items("/batches") if b["name"] == "Retained POC replay"), None)
    if not batch:
        save_manifest(manifest)
        raise RuntimeError("Demo users and teams exist, but Retained POC replay is missing. "
                           "Enable the documented POC seed in a fresh workspace or assign batch grants manually.")
    for team in team_records:
        if not any(g.get("team_id") == team["id"] and g["role"] == team["role"] for g in batch["grants"]):
            admin.call("POST", f"/batches/{batch['id']}/grants", {"team_id": team["id"], "role": team["role"]})
    manifest["batch"] = {"id": batch["id"], "name": batch["name"]}
    save_manifest(manifest)
    lines = ["# Local demo login details", "", f"Open [{base}]({base}), sign out if needed, then choose **Sign in**.", "",
             "Generated for this local workspace only. This file is ignored by Git and excluded from Docker builds.", "",
             "| Name | Email | Password | Workspace role |", "|---|---|---|---|"]
    for person in manifest["accounts"]:
        lines.append(f"| {person['name']} | `{person['email']}` | `{person['password']}` | {person['role']} |")
    lines += ["", f"Open the [five-task example batch]({base}/#/batches/{batch['id']}) after signing in.", "",
              "| Team | Members | Access to the example batch |", "|---|---|---|"]
    for team in team_records:
        lines.append(f"| {team['name']} | {', '.join(people[k]['name'] for k in team['members'])} | {team['role']} |")
    lines += ["", "Admin manages users and taxonomy publication. Manager manages datasets and batches. "
              "Reviewers inspect trajectories, add feedback and propose labels. Viewer reads and exports. "
              "Reviewer/viewer batch access comes from their team grants.", "",
              "Reseed with `python3 platform/scripts/seed_demo.py`. Existing passwords and saved reviews are retained; "
              "missing demo team memberships and batch grants are restored. No model jobs are started.", ""]
    private_write(GUIDE, "\n".join(lines))
    print(f"Ready: {len(people)} demo users, {len(team_records)} teams, {batch['name']}.")
    print(f"Login details: {GUIDE}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-credentials", type=Path)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    url = urlsplit(base)
    if url.scheme not in ("http", "https") or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.username or url.password or url.path or url.query or url.fragment:
        parser.error("Demo seeding is restricted to a local loopback origin.")
    try:
        seed(base, args.admin_credentials)
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"Demo seed stopped: {exc}\n")


if __name__ == "__main__":
    main()
