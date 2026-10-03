"""Cost/evidence boundary checks using fakes, with no paid provider requests."""

import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from app.core import config
from app.worker import review_backends as review
from app.worker.taxonomy_backend import consolidate_drafts


def fixture_task():
    return json.loads((config.PROJECT_ROOT / "poc/runs/latest/run.json").read_text())["tasks"][0]


def test_image_provenance_separates_source_delivery_and_model_claims():
    task = {
        "steps": [
            {"step_id": str(i), "screenshot": f"assets/{i}.png", "evidence_refs": [f"frame_{i}"]} for i in range(1, 5)
        ]
    }
    result = {"steps": [{"evidence_refs": ["frame_1", "frame_3", "frame_4"]}], "episodes": []}
    provenance = review._image_provenance(task, ["1", "2", "3"], result)
    assert provenance["source_image_step_ids"] == ["1", "2", "3", "4"]
    assert provenance["supplied_image_step_ids"] == ["1", "2", "3"]
    assert provenance["cited_image_step_ids"] == ["1", "3"]
    assert provenance["omitted_image_step_ids"] == ["4"]
    assert provenance["image_selection"] == "sampled"
    assert review._image_provenance(task, [])["evidence_mode"] == "text_only"


def test_visual_review_loads_more_than_five_authorized_frames(monkeypatch):
    from app.core import storage

    payload = b"controlled-test-frame"
    monkeypatch.setattr(storage, "create_artifact_store", lambda settings: SimpleNamespace(get=lambda key: payload))
    task = {"steps": [{"step_id": str(i), "screenshot": f"assets/{i}.png"} for i in range(1, 10)]}
    artifacts = [
        {
            "relative_path": step["screenshot"],
            "media_type": "image/png",
            "object_key": f"authorized/{step['step_id']}",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        for step in task["steps"]
    ]
    images = review._images(task, 32, artifacts)
    assert [image[0] for image in images] == [str(i) for i in range(1, 10)]
    assert len(review._images(task, 5, artifacts)) == 5


def fake_provider(monkeypatch, raw, cost=0.012):
    calls = []
    provider = SimpleNamespace(
        cost_per_token=lambda **kw: (0.0001, 0.0002),
        completion_cost=lambda **kw: cost,
        completion=lambda **kw: (
            calls.append(kw)
            or SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=raw))],
                usage=SimpleNamespace(model_dump=lambda: {"prompt_tokens": 123, "completion_tokens": 45}),
                model="test-only",
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "litellm", provider)
    monkeypatch.setenv("ALLOW_HOSTED_INFERENCE", "true")
    return provider, calls


def test_replay_preserves_original_and_reports_zero_new_cost():
    task = fixture_task()
    output = review.execute_review(
        backend="saved_replay", preset_revision={}, task_snapshot=task, review_kind=task["review"]["review_kind"]
    )
    assert output["review"] == task["review"]
    assert output["review"] is not task["review"]
    assert output["usage"]["estimated_usd"] == 0
    assert output["provenance"]["new_inference"] is False
    assert output["provenance"]["original_usage"] == task["usage"]


def test_hosted_opt_out_makes_no_request(monkeypatch):
    provider, calls = fake_provider(monkeypatch, "{}")
    monkeypatch.setenv("ALLOW_HOSTED_INFERENCE", "false")
    with pytest.raises(review.ReviewBackendError, match="disabled"):
        review.execute_review(
            backend="model_api",
            preset_revision={"model": "test", "budget_usd": 1},
            task_snapshot=fixture_task(),
            review_kind="failure_analysis",
        )
    assert not calls


def test_unknown_price_blocks_before_request(monkeypatch):
    provider, calls = fake_provider(monkeypatch, "{}")

    def unknown(**kwargs):
        raise KeyError("no price")

    provider.cost_per_token = unknown
    with pytest.raises(review.ReviewBackendError, match="pricing is unknown"):
        review.execute_review(
            backend="model_api",
            preset_revision={"model": "test", "budget_usd": 1},
            task_snapshot=fixture_task(),
            review_kind="failure_analysis",
        )
    assert not calls


def test_invalid_json_retains_incurred_usage(monkeypatch):
    _, calls = fake_provider(monkeypatch, "not valid json")
    with pytest.raises(review.ReviewBackendError) as error:
        review.execute_review(
            backend="model_api",
            preset_revision={"model": "test", "budget_usd": 1, "configuration": {"max_images": 0}},
            task_snapshot=fixture_task(),
            review_kind="failure_analysis",
        )
    assert len(calls) == 1
    assert error.value.usage["estimated_usd"] == 0.012
    assert error.value.usage["input_tokens"] == 123


def test_frame_citations_require_attached_images():
    task = fixture_task()
    task["review"]["schema_version"] = "2"
    source_order = {str(step["step_id"]): i for i, step in enumerate(task["steps"])}
    episodes = sorted(task["review"]["episodes"], key=lambda e: min(source_order[s] for s in e["onset_step_ids"]))
    for i, episode in enumerate(episodes, 1):
        episode["problem_number"] = i
        episode["first_observed_step_id"] = min(episode["onset_step_ids"], key=source_order.get)
    assert any(str(ref).startswith("frame_") for step in task["review"]["steps"] for ref in step["evidence_refs"])
    with pytest.raises(review.ReviewBackendError, match="uninspected evidence"):
        review._validate(task["review"], task, task["review"]["review_kind"], inspected_step_ids=[])


def test_invalid_taxonomy_draft_retains_incurred_usage(monkeypatch):
    _, calls = fake_provider(monkeypatch, '{"labels": [],"mappings": [],"unresolved": []}')
    with pytest.raises(review.ReviewBackendError) as error:
        consolidate_drafts(
            preset_revision={"backend": "model_api", "model": "test", "budget_usd": 1},
            base_content={"labels": [{"id": "existing", "name": "A", "description": "B"}]},
            proposals=[],
        )
    assert len(calls) == 1
    assert error.value.usage["estimated_usd"] == 0.012


def test_imported_screenshot_requires_trusted_artifact_and_checksum(monkeypatch):
    from app.core import storage

    data = b"fixture image bytes"
    reads = []
    store = SimpleNamespace(get=lambda key: (reads.append(key) or data))
    monkeypatch.setattr(storage, "create_artifact_store", lambda settings: store)
    task = {"steps": [{"step_id": "1", "screenshot": "assets/task/step.png", "object_key": "untrusted/source/key"}]}
    # An imported task cannot grant itself access to object storage.
    assert review._images(task, 3) == []
    assert not reads
    authorized = {
        "relative_path": "assets/task/step.png",
        "media_type": "image/png",
        "object_key": "authorized/revision/key",
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    assert review._images(task, 3, [authorized]) == [("1", "image/png", data)]
    assert reads == ["authorized/revision/key"]
    with pytest.raises(review.ReviewBackendError, match="checksum"):
        review._images(task, 3, [{**authorized, "sha256": "mismatch"}])
    reads.clear()
    assert review._images(task, 0, [authorized]) == []
    assert not reads
