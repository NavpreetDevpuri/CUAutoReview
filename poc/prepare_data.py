#!/usr/bin/env python3
"""Prepare a five-task OSWorld-Verified POC batch using bounded ZIP ranges.

This script downloads only the ZIP central directory and selected task members.
It does not download the 3.4 GB archive or the per-task MP4 recordings.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parent
DATA_ROOT = POC_ROOT / "data"
SOURCE_ROOT = DATA_ROOT / "source" / "osworld-verified"
EXISTING_ROOT = POC_ROOT.parent / "reference" / "examples" / "osworld-verified"

DATASET_COMMIT = "5473c39e42a538a187a9b2c2b499db59d560fd8c"
TASK_COMMIT = "b138d348256078fa634fc3b73567a7337c793e6b"
ARCHIVE_URL = (
    "https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/resolve/"
    f"{DATASET_COMMIT}/o3_15steps.zip"
)
ARCHIVE_BYTES = 3_408_011_289
ARCHIVE_SHA256 = "976c2028235156cd767ebf723c5b301761ae7c951afb9c507f1ac1ef9b014b2b"
CD_START, CD_END = 3_406_999_538, 3_408_011_266
EOCD_START, EOCD_END = 3_408_011_267, 3_408_011_288
MAX_SELECTED_UNCOMPRESSED = 15_000_000

SELECTED = [
    # The archive's final score is retained verbatim; category comes from it.
    {"app": "gimp", "task_id": "b148e375-fe0b-4bec-90e7-38632b0d73c2"},
    {"app": "libreoffice_calc", "task_id": "6e99a1ad-07d2-4b66-a1ce-ece6d99c20a5"},
    {"app": "chrome", "task_id": "368d9ba4-203c-40c1-9fa3-da2f1430ce63"},
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def curl_range(start: int, end: int) -> bytes:
    """Fetch exactly one bounded inclusive HTTP byte range."""
    with tempfile.NamedTemporaryFile(prefix="osworld-range-") as output:
        command = [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            "10",
            "--max-time",
            "90",
            "--max-filesize",
            str(MAX_SELECTED_UNCOMPRESSED),
            "--range",
            f"{start}-{end}",
            "--header",
            "Accept-Encoding: identity",
            "--output",
            output.name,
            "--write-out",
            "%{http_code}",
            ARCHIVE_URL,
        ]
        status = subprocess.run(command, check=True, capture_output=True, text=True).stdout
        output.seek(0)
        data = output.read()
    expected = end - start + 1
    if status != "206" or len(data) != expected:
        raise RuntimeError(
            f"Range {start}-{end} returned HTTP {status} and {len(data)} bytes; expected 206 and {expected}"
        )
    return data


def curl_url(url: str, max_bytes: int = 100_000) -> bytes:
    with tempfile.NamedTemporaryFile(prefix="osworld-source-") as output:
        command = [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            "10",
            "--max-time",
            "60",
            "--max-filesize",
            str(max_bytes),
            "--output",
            output.name,
            url,
        ]
        subprocess.run(command, check=True)
        output.seek(0)
        return output.read()


def parse_central_directory(directory: bytes, eocd: bytes) -> list[dict]:
    if len(eocd) != 22 or eocd[:4] != b"PK\x05\x06":
        raise RuntimeError("Unexpected ZIP end-of-central-directory record")
    fields = struct.unpack("<4s4H2LH", eocd)
    _, disk, cd_disk, count_disk, entry_count, cd_size, cd_offset, comment_len = fields
    if (disk, cd_disk, count_disk, comment_len) != (0, 0, entry_count, 0):
        raise RuntimeError("Unexpected multi-disk or commented ZIP archive")
    if cd_offset != CD_START or cd_size != len(directory):
        raise RuntimeError("ZIP central-directory metadata differs from the pinned range")

    entries = []
    offset = 0
    for _ in range(entry_count):
        values = struct.unpack_from("<4s6H3L5H2L", directory, offset)
        if values[0] != b"PK\x01\x02":
            raise RuntimeError(f"Bad central-directory signature at byte {offset}")
        (
            _, made_by, needed, flags, method, mtime, mdate, crc, compressed_size,
            uncompressed_size, name_len, extra_len, comment_len, disk_start,
            internal_attr, external_attr, local_header_offset,
        ) = values
        name_bytes = directory[offset + 46 : offset + 46 + name_len]
        name = name_bytes.decode("utf-8")
        entries.append(
            {
                "name": name,
                "crc32": crc,
                "compressed_size": compressed_size,
                "uncompressed_size": uncompressed_size,
                "local_header_offset": local_header_offset,
                "method": method,
                "flags": flags,
                "name_len": name_len,
            }
        )
        offset += 46 + name_len + extra_len + comment_len
    if offset != len(directory):
        raise RuntimeError("Central-directory parse did not consume the full pinned range")
    return entries


def selected_entries(entries: list[dict]) -> dict[str, list[dict]]:
    output = {}
    total = 0
    for selected in SELECTED:
        prefix = f"o3_15steps/{selected['app']}/{selected['task_id']}/"
        members = [entry for entry in entries if entry["name"].startswith(prefix)]
        required = [
            entry
            for entry in members
            if entry["name"].endswith(("/traj.jsonl", "/result.txt", "/runtime.log"))
            or "/step_" in entry["name"] and entry["name"].endswith(".png")
        ]
        if not any(item["name"].endswith("/traj.jsonl") for item in required):
            raise RuntimeError(f"No trajectory in source directory {prefix}")
        if not any(item["name"].endswith("/result.txt") for item in required):
            raise RuntimeError(f"No score in source directory {prefix}")
        total += sum(item["uncompressed_size"] for item in required)
        output[selected["task_id"]] = required
    if total > MAX_SELECTED_UNCOMPRESSED:
        raise RuntimeError(f"Selected files total {total} bytes, over the 15 MB limit")
    return output


def extract_member(entry: dict) -> tuple[dict, bytes]:
    start = entry["local_header_offset"]
    header = curl_range(start, start + 29)
    fields = struct.unpack("<4s5H3L2H", header)
    if fields[0] != b"PK\x03\x04":
        raise RuntimeError(f"Bad local header for {entry['name']}")
    local_name_len, local_extra_len = fields[-2:]
    if local_name_len != entry["name_len"]:
        raise RuntimeError(f"Filename length mismatch for {entry['name']}")
    data_start = start + 30 + local_name_len + local_extra_len
    compressed = curl_range(data_start, data_start + entry["compressed_size"] - 1)
    if entry["method"] == 0:
        data = compressed
    elif entry["method"] == 8:
        data = zlib.decompress(compressed, -15)
    else:
        raise RuntimeError(f"Unsupported ZIP method {entry['method']} for {entry['name']}")
    if len(data) != entry["uncompressed_size"] or zlib.crc32(data) != entry["crc32"]:
        raise RuntimeError(f"Size or ZIP CRC mismatch for {entry['name']}")
    return (
        {
            "archive_member": entry["name"],
            "data_http_range": f"bytes={data_start}-{data_start + entry['compressed_size'] - 1}",
            "compressed_bytes": entry["compressed_size"],
            "uncompressed_bytes": len(data),
            "zip_crc32": f"{entry['crc32']:08x}",
            "zip_crc_verified": True,
            "sha256": sha256(data),
        },
        data,
    )


def parse_jsonl(data: bytes) -> list[dict]:
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def action_text(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def first_text(record: dict, names: tuple[str, ...]):
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            return value
    action = record.get("action")
    if isinstance(action, dict):
        for name in names:
            value = action.get(name)
            if isinstance(value, str) and value.strip():
                return value
    return None


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def copy_existing_examples():
    for task_id in (
        "66399b0d-8fda-4618-95c4-bfc6191617e9",
        "0e47de2a-32e0-456c-a366-8c607ef7a9d2",
    ):
        target = SOURCE_ROOT / task_id
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(EXISTING_ROOT / task_id, target)


def main():
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    copy_existing_examples()

    central = curl_range(CD_START, CD_END)
    eocd = curl_range(EOCD_START, EOCD_END)
    entries = parse_central_directory(central, eocd)
    selected = selected_entries(entries)
    member_bytes = {}

    all_entries = [entry for group in selected.values() for entry in group]
    # Fetch member headers and bodies in two stages. Each request is a bounded range.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        extracted = list(pool.map(extract_member, all_entries))
    for entry, (file_metadata, data) in zip(all_entries, extracted):
        member_bytes[entry["name"]] = (file_metadata, data)

    batch_tasks = []
    acquired_at = datetime.now(timezone.utc).isoformat()
    dataset_card_url = (
        "https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/raw/"
        f"{DATASET_COMMIT}/README.md"
    )
    task_license_url = f"https://raw.githubusercontent.com/xlang-ai/OSWorld/{TASK_COMMIT}/LICENSE"
    # These byte-identical shared references were already retrieved with the two local examples.
    dataset_card = (EXISTING_ROOT / "66399b0d-8fda-4618-95c4-bfc6191617e9" / "dataset-card.md").read_bytes()
    task_license = (EXISTING_ROOT / "66399b0d-8fda-4618-95c4-bfc6191617e9" / "LICENSE-task-source.txt").read_bytes()
    for selected_task in SELECTED:
        app, task_id = selected_task["app"], selected_task["task_id"]
        source_dir = SOURCE_ROOT / task_id
        source_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"o3_15steps/{app}/{task_id}/"
        files_metadata = {}
        for entry in selected[task_id]:
            metadata, data = member_bytes[entry["name"]]
            name = entry["name"].removeprefix(prefix)
            (source_dir / name).write_bytes(data)
            files_metadata[name] = metadata

        task_url = (
            f"https://raw.githubusercontent.com/xlang-ai/OSWorld/{TASK_COMMIT}/"
            f"evaluation_examples/examples/{app}/{task_id}.json"
        )
        task_json = curl_url(task_url)
        for name, data, url in (
            ("task.json", task_json, task_url),
            ("dataset-card.md", dataset_card, dataset_card_url),
            ("LICENSE-task-source.txt", task_license, task_license_url),
        ):
            (source_dir / name).write_bytes(data)
            files_metadata[name] = {"source_url": url, "bytes": len(data), "sha256": sha256(data)}

        task = json.loads(task_json)
        score_bytes = (source_dir / "result.txt").read_bytes()
        score_text = score_bytes.decode("utf-8").strip()
        try:
            score = float(score_text)
        except ValueError:
            score = None
        if score == 1.0:
            outcome = "passed"
        elif score == 0.0:
            outcome = "failed"
        else:
            outcome = "unknown"

        trajectory = parse_jsonl((source_dir / "traj.jsonl").read_bytes())
        screenshot_names = sorted(
            (name for name in files_metadata if name.startswith("step_") and name.endswith(".png")),
            key=lambda value: int(value.split("_", 2)[1]),
        )
        screenshots_by_step = {int(name.split("_", 2)[1]): name for name in screenshot_names}
        steps = []
        for index, record in enumerate(trajectory, start=1):
            step_num = record.get("step_num", record.get("step", index))
            if not isinstance(step_num, int):
                step_num = index
            shot_name = screenshots_by_step.get(step_num)
            image_path = f"data/source/osworld-verified/{task_id}/{shot_name}" if shot_name else None
            refs = [f"event_{step_num}"]
            if image_path:
                refs.append(f"frame_{step_num}")
            action = record.get("action", record.get("response", record))
            steps.append(
                {
                    "step_id": str(step_num),
                    "intent": first_text(record, ("comment", "thought", "intent", "description")),
                    "action": action_text(action),
                    "observation": first_text(record, ("observation", "obs", "result")),
                    "screenshot": image_path,
                    "evidence_refs": refs,
                }
            )

        archive_task_members = [entry["name"] for entry in selected[task_id]]
        found_frame_steps = sorted(screenshots_by_step)
        source_action_steps = [int(step["step_id"]) for step in steps]
        instruction = task.get("instruction") or task.get("task_instruction") or ""
        task_title = task.get("task_name") or task.get("title") or instruction or task_id
        provenance = {
            "schema_version": 1,
            "acquired_at_utc": acquired_at,
            "task_id": task_id,
            "dataset": {
                "repository": "xlangai/ubuntu_osworld_verified_trajs",
                "commit": DATASET_COMMIT,
                "dataset_url": "https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs",
                "archive_url": ARCHIVE_URL,
                "archive_bytes": ARCHIVE_BYTES,
                "archive_sha256_as_declared_by_huggingface_lfs": ARCHIVE_SHA256,
                "full_archive_checksum_verified_locally": False,
                "acquisition_method": "HTTP Range reads of ZIP central directory, local headers, and selected members; ZIP CRC32 and uncompressed length checked. Full archive and recording.mp4 not downloaded.",
                "central_directory_range": f"bytes={CD_START}-{CD_END}",
                "end_of_central_directory_range": f"bytes={EOCD_START}-{EOCD_END}",
            },
            "rollout": {
                "agent_model_as_published": "o3",
                "step_budget_as_archive_name": 15,
                "recorded_action_count": len(trajectory),
                "recorded_final_score_text": score_text,
                "recorded_final_score": score,
                "score_source": "result.txt",
                "human_failure_annotations": "absent from selected task directory; no human failure labels supplied by this example",
            },
            "task_definition": {
                "source_url": task_url,
                "source_commit": TASK_COMMIT,
                "matches_rollout_task_id": task.get("id") == task_id or task.get("task_id") == task_id,
                "exact_historical_match_verified": False,
                "limitation": "This is the pinned current public task definition, not proven to be the exact definition or evaluator used for the July 2025 rollout.",
            },
            "screenshot_coverage": {
                "recorded_action_steps": source_action_steps,
                "screenshots_available_in_selected_archive_members": found_frame_steps,
                "screenshots_downloaded": found_frame_steps,
                "screenshots_missing_or_not_present_in_archive": sorted(set(source_action_steps) - set(found_frame_steps)),
                "recording_mp4_downloaded": False,
            },
            "licensing": {
                "trajectory_dataset_declared_license": "MIT (dataset-card YAML: license: mit)",
                "dataset_card_url": dataset_card_url,
                "task_repository_license": "Apache-2.0",
                "task_repository_license_url": task_license_url,
                "third_party_screenshot_or_document_rights": "Not individually itemized by the dataset card.",
            },
            "files": files_metadata,
        }
        write_json(source_dir / "provenance.json", provenance)

        coverage_notes = [
            f"Archive label is 15steps; source traj.jsonl contains {len(trajectory)} recorded actions.",
            f"Downloaded {len(found_frame_steps)} available recorded step screenshots: {', '.join(map(str, found_frame_steps))}.",
            "The archive recording.mp4 was not downloaded.",
            "Current task definition/evaluator pin is not proven to match the historical rollout environment.",
            "No human-authored failure diagnosis or recovery annotation is included.",
        ]
        missing_frames = sorted(set(source_action_steps) - set(found_frame_steps))
        if missing_frames:
            coverage_notes.append(
                "No selected source step screenshot for recorded steps: " + ", ".join(map(str, missing_frames)) + "."
            )
        batch_tasks.append(
            {
                "task_id": task_id,
                "title": task_title,
                "instruction": instruction,
                "outcome": outcome,
                "score": score,
                "source": {
                    "dataset": "OSWorld-Verified",
                    "task_id": task_id,
                    "application": app,
                    "agent_model": "o3",
                    "archive": ARCHIVE_URL,
                    "dataset_commit": DATASET_COMMIT,
                    "task_source_commit": TASK_COMMIT,
                    "task_definition": f"data/source/osworld-verified/{task_id}/task.json",
                    "trajectory": f"data/source/osworld-verified/{task_id}/traj.jsonl",
                    "score_file": f"data/source/osworld-verified/{task_id}/result.txt",
                    "runtime_log": f"data/source/osworld-verified/{task_id}/runtime.log",
                    "provenance_file": f"data/source/osworld-verified/{task_id}/provenance.json",
                },
                "coverage_notes": coverage_notes,
                "steps": steps,
            }
        )

    # The two established local failures have only three selected screenshots each.
    old_ids = [
        "66399b0d-8fda-4618-95c4-bfc6191617e9",
        "0e47de2a-32e0-456c-a366-8c607ef7a9d2",
    ]
    for task_id in old_ids:
        source_dir = SOURCE_ROOT / task_id
        task = json.loads((source_dir / "task.json").read_text(encoding="utf-8"))
        score_text = (source_dir / "result.txt").read_text(encoding="utf-8").strip()
        score = float(score_text)
        trajectory = parse_jsonl((source_dir / "traj.jsonl").read_bytes())
        selected_shots = {
            int(path.name.split("_", 2)[1]): path.name
            for path in source_dir.glob("step_*.png")
        }
        steps = []
        for index, record in enumerate(trajectory, start=1):
            step_num = record.get("step_num", record.get("step", index))
            if not isinstance(step_num, int):
                step_num = index
            shot_name = selected_shots.get(step_num)
            image_path = f"data/source/osworld-verified/{task_id}/{shot_name}" if shot_name else None
            refs = [f"event_{step_num}"]
            if image_path:
                refs.append(f"frame_{step_num}")
            steps.append(
                {
                    "step_id": str(step_num),
                    "intent": first_text(record, ("comment", "thought", "intent", "description")),
                    "action": action_text(record.get("action", record.get("response", record))),
                    "observation": first_text(record, ("observation", "obs", "result")),
                    "screenshot": image_path,
                    "evidence_refs": refs,
                }
            )
        instruction = task.get("instruction") or task.get("task_instruction") or ""
        task_title = task.get("task_name") or task.get("title") or instruction or task_id
        source = {
            "dataset": "OSWorld-Verified",
            "task_id": task_id,
            "application": "libreoffice_writer",
            "agent_model": "o3",
            "archive": ARCHIVE_URL,
            "dataset_commit": DATASET_COMMIT,
            "task_source_commit": TASK_COMMIT,
            "task_definition": f"data/source/osworld-verified/{task_id}/task.json",
            "trajectory": f"data/source/osworld-verified/{task_id}/traj.jsonl",
            "score_file": f"data/source/osworld-verified/{task_id}/result.txt",
            "runtime_log": f"data/source/osworld-verified/{task_id}/runtime.log",
            "provenance_file": f"data/source/osworld-verified/{task_id}/provenance.json",
        }
        available_shots = sorted(selected_shots)
        missing_frames = sorted(set(range(1, len(trajectory) + 1)) - set(available_shots))
        coverage_notes = [
            f"Archive label is 15steps; source traj.jsonl contains {len(trajectory)} recorded actions.",
            f"Three selected screenshots are retained for source steps {', '.join(map(str, available_shots))}.",
            "The archive recording.mp4 and all other step screenshots were not downloaded.",
            "Current task definition/evaluator pin is not proven to match the historical rollout environment.",
            "No human-authored failure diagnosis or recovery annotation is included.",
        ]
        if missing_frames:
            coverage_notes.append(
                "No selected source screenshot for recorded steps: " + ", ".join(map(str, missing_frames)) + "."
            )
        batch_tasks.append(
            {
                "task_id": task_id,
                "title": task_title,
                "instruction": instruction,
                "outcome": "failed",
                "score": score,
                "source": source,
                "coverage_notes": coverage_notes,
                "steps": steps,
            }
        )

    batch_tasks.sort(key=lambda item: (item["source"]["application"], item["task_id"]))
    notes = [
        "Five distinct OSWorld-Verified task IDs from public o3_15steps rollouts. Source task, trace, score, runtime log where selected, and provenance are retained under data/source/osworld-verified/.",
        "The score in each result.txt is the recorded terminal grade. Per-step reward/done values are not substituted for that grade.",
        "Outcome categories are derived only from source result.txt values 0/0.0 or 1/1.0; other values are unknown.",
        "These are source-scored examples, not human-adjudicated labels. No human gold annotation is included or inferred.",
        "Dataset revision is pinned at 5473c39e42a538a187a9b2c2b499db59d560fd8c. Task definitions are from OSWorld commit b138d348256078fa634fc3b73567a7337c793e6b and are not verified historical evaluator matches.",
        "The 3.4 GB archive was not downloaded. ZIP Range reads fetched the central directory plus selected trajectory, score, runtime, and step screenshot members; MP4 recordings were omitted.",
        "Selected screenshots are linked per step. Screenshot coverage notes list missing or unselected frames, including the two pre-existing failures with sparse frames.",
        "The dataset card declares MIT, and OSWorld task source declares Apache-2.0. The dataset card does not itemize third-party document or screenshot rights.",
    ]
    write_json(DATA_ROOT / "batch.json", {
        "schema_version": "1",
        "batch_id": "osworld-five",
        "notes": notes,
        "tasks": batch_tasks,
    })
    print(f"Wrote {DATA_ROOT / 'batch.json'} with {len(batch_tasks)} tasks")
    print(f"Selected uncompressed members: {sum(item['uncompressed_size'] for group in selected.values() for item in group):,} bytes")


if __name__ == "__main__":
    main()
