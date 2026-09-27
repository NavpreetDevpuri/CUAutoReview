"""Focused contract tests for the local trajectory-review POC."""
import concurrent.futures
import copy
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path


POC_DIR = Path(__file__).resolve().parents[1]
if str(POC_DIR) not in sys.path:
    sys.path.insert(0, str(POC_DIR))

import label_tools
import run


def sample_task(outcome="failed", task_id="task-1"):
    return {
        "task_id": task_id,
        "outcome": outcome,
        "steps": [
            {"step_id": "s1", "evidence_refs": ["event-1", "frame-1"]},
            {"step_id": "s2", "evidence_refs": ["event-2"]},
        ],
    }


def sample_review():
    return {
        "review_kind": "failure_analysis",
        "summary": "A supported mistake was corrected.",
        "result": "issues_observed",
        "coverage_notes": [],
        "steps": [
            {
                "step_id": "s1",
                "review_status": "reviewed",
                "intent": {"kind": "unknown", "text": ""},
                "action": "Clicked the control.",
                "observed_ui": "The dialog remained open.",
                "effect": "The requested change was not confirmed.",
                "assessment": "Possible incomplete action.",
                "evidence_refs": ["event-1"],
                "episode_refs": ["e1"],
            },
            {
                "step_id": "s2",
                "review_status": "reviewed",
                "intent": {"kind": "unknown", "text": ""},
                "action": "Confirmed the change.",
                "observed_ui": "The dialog closed.",
                "effect": "The change was saved.",
                "assessment": "Recovery is supported.",
                "evidence_refs": ["event-2"],
                "episode_refs": [],
            },
        ],
        "episodes": [
            {
                "episode_id": "e1",
                "mechanism": "The action was not confirmed.",
                "onset_step_ids": ["s1"],
                "recovery": {
                    "status": "none_observed",
                    "step_ids": [],
                    "evidence_refs": [],
                    "rationale": "Recovery is assessed independently.",
                },
                "outcome_contribution": "uncertain",
                "label_id": "",
                "label_name": "",
                "evidence_refs": ["event-1"],
                "uncertainty": "The final outcome contribution is unclear.",
            }
        ],
    }


def sample_review_v2():
    review = sample_review()
    review["schema_version"] = "2"
    review["episodes"][0].update(problem_number=1, first_observed_step_id="s1")
    return review


class ReviewContractTests(unittest.TestCase):
    def test_new_invocations_use_version_two_and_legacy_schema_stays_unversioned(self):
        self.assertEqual(run.REVIEW["properties"]["schema_version"]["enum"], ["2"])
        self.assertNotIn("schema_version", run.REVIEW_V1["properties"])

    def test_rejects_missing_or_duplicate_step_annotations(self):
        task = sample_task()

        missing = sample_review()
        missing["steps"].pop()
        with self.subTest(case="missing"):
            with self.assertRaisesRegex(ValueError, "Missing, duplicate or reordered"):
                run.validate_review(missing, task, {"proposals": []})

        duplicate = sample_review()
        duplicate["steps"][1] = copy.deepcopy(duplicate["steps"][0])
        with self.subTest(case="duplicate"):
            with self.assertRaisesRegex(ValueError, "Missing, duplicate or reordered"):
                run.validate_review(duplicate, task, {"proposals": []})

    def test_rejects_unknown_step_episode_and_recovery_evidence(self):
        task = sample_task()

        invalid_step_evidence = sample_review()
        invalid_step_evidence["steps"][0]["evidence_refs"] = ["made-up"]

        invalid_episode_evidence = sample_review()
        invalid_episode_evidence["episodes"][0]["evidence_refs"] = ["made-up"]

        invalid_recovery_evidence = sample_review()
        invalid_recovery_evidence["episodes"][0]["recovery"].update(
            status="recovered", step_ids=["s2"], evidence_refs=["made-up"]
        )

        for case, review in (
            ("step", invalid_step_evidence),
            ("episode", invalid_episode_evidence),
            ("recovery", invalid_recovery_evidence),
        ):
            with self.subTest(case=case):
                with self.assertRaisesRegex(ValueError, "Invalid .* evidence"):
                    run.validate_review(review, task, {"proposals": []})

    def test_recovery_and_failure_contribution_are_independent(self):
        task = sample_task()

        recovered_but_contributing = sample_review()
        recovered_but_contributing["episodes"][0]["recovery"].update(
            status="recovered", step_ids=["s2"], evidence_refs=["event-2"]
        )
        recovered_but_contributing["episodes"][0]["outcome_contribution"] = "contributing"

        no_recovery_but_contributing = sample_review()
        no_recovery_but_contributing["episodes"][0]["outcome_contribution"] = "contributing"

        recovered_but_noncontributing = copy.deepcopy(recovered_but_contributing)
        recovered_but_noncontributing["episodes"][0]["outcome_contribution"] = "noncontributing"

        for review in (recovered_but_contributing, no_recovery_but_contributing, recovered_but_noncontributing):
            run.validate_review(review, task, {"proposals": []})

    def test_recovery_cannot_precede_onset_but_may_share_onset_step(self):
        task = sample_task()

        mixed_effect = sample_review()
        mixed_effect["episodes"][0]["recovery"].update(
            status="recovered", step_ids=["s1"], evidence_refs=["event-1"]
        )
        run.validate_review(mixed_effect, task, {"proposals": []})

        precedes_onset = sample_review()
        precedes_onset["steps"][0]["episode_refs"] = []
        precedes_onset["steps"][1]["episode_refs"] = ["e1"]
        precedes_onset["episodes"][0].update(onset_step_ids=["s2"])
        precedes_onset["episodes"][0]["recovery"].update(
            status="recovered", step_ids=["s1"], evidence_refs=["event-1"]
        )
        with self.assertRaisesRegex(ValueError, "Recovery step precedes episode onset"):
            run.validate_review(precedes_onset, task, {"proposals": []})

    def test_v2_orders_problems_by_source_step_order_not_lexically(self):
        task = sample_task()
        task["steps"] = [
            {"step_id": "10", "evidence_refs": ["event-1"]},
            {"step_id": "2", "evidence_refs": ["event-2"]},
        ]
        review = sample_review_v2()
        review["steps"][0]["step_id"] = "10"
        review["steps"][1]["step_id"] = "2"
        review["steps"][0]["episode_refs"] = ["e1"]
        review["steps"][1]["episode_refs"] = ["e1"]
        # Deliberately reverse the onset list: trajectory order still makes 10 first.
        review["episodes"][0].update(
            onset_step_ids=["2", "10"], first_observed_step_id="10"
        )

        run.validate_review(review, task, {"proposals": []})

    def test_v2_allows_shared_step_and_onset_recovery_overlap(self):
        task = sample_task()
        review = sample_review_v2()
        first = review["episodes"][0]
        first["recovery"].update(
            status="recovered", step_ids=["s2"], evidence_refs=["event-2"]
        )
        second = copy.deepcopy(first)
        second.update(
            episode_id="e2",
            problem_number=2,
            first_observed_step_id="s2",
            onset_step_ids=["s2"],
            evidence_refs=["event-2"],
        )
        second["recovery"].update(status="partial", step_ids=["s2"])
        review["episodes"].append(second)
        review["steps"][1]["episode_refs"] = ["e1", "e2"]

        run.validate_review(review, task, {"proposals": []})

    def test_v2_allows_related_context_link_on_another_episodes_onset(self):
        task = sample_task()
        task["steps"].append({"step_id": "s3", "evidence_refs": ["event-3"]})
        review = sample_review_v2()
        first = review["episodes"][0]
        first["recovery"].update(
            status="recovered", step_ids=["s3"], evidence_refs=["event-3"]
        )
        second = copy.deepcopy(first)
        second.update(
            episode_id="e2",
            problem_number=2,
            first_observed_step_id="s2",
            onset_step_ids=["s2"],
            evidence_refs=["event-2"],
        )
        second["recovery"].update(
            status="none_observed", step_ids=[], evidence_refs=[]
        )
        review["episodes"].append(second)
        review["steps"].append(
            {
                "step_id": "s3",
                "review_status": "reviewed",
                "intent": {"kind": "unknown", "text": ""},
                "action": "",
                "observed_ui": "",
                "effect": "",
                "assessment": "",
                "evidence_refs": ["event-3"],
                "episode_refs": ["e1"],
            }
        )
        # s2 is related context for e1 and the first onset flag for e2.
        review["steps"][1]["episode_refs"] = ["e1", "e2"]

        run.validate_review(review, task, {"proposals": []})

    def test_v2_ties_use_episode_order_and_numbers_must_be_contiguous(self):
        task = sample_task()
        review = sample_review_v2()
        second = copy.deepcopy(review["episodes"][0])
        second.update(episode_id="e2", problem_number=2)
        review["episodes"].append(second)
        review["steps"][0]["episode_refs"] = ["e1", "e2"]

        run.validate_review(review, task, {"proposals": []})

        duplicate = copy.deepcopy(review)
        duplicate["episodes"][1]["problem_number"] = 1
        with self.assertRaisesRegex(ValueError, "Duplicate problem_number"):
            run.validate_review(duplicate, task, {"proposals": []})

        gap = copy.deepcopy(review)
        gap["episodes"][1]["problem_number"] = 3
        with self.assertRaisesRegex(ValueError, "contiguous in first-observed order"):
            run.validate_review(gap, task, {"proposals": []})

        wrong_order = copy.deepcopy(review)
        wrong_order["episodes"][0]["onset_step_ids"] = ["s2"]
        wrong_order["episodes"][0]["first_observed_step_id"] = "s2"
        wrong_order["episodes"][1]["onset_step_ids"] = ["s1"]
        wrong_order["episodes"][1]["first_observed_step_id"] = "s1"
        wrong_order["episodes"][0]["problem_number"] = 1
        wrong_order["episodes"][1]["problem_number"] = 2
        wrong_order["steps"][0]["episode_refs"] = ["e2"]
        wrong_order["steps"][1]["episode_refs"] = ["e1"]
        with self.assertRaisesRegex(ValueError, "contiguous in first-observed order"):
            run.validate_review(wrong_order, task, {"proposals": []})

    def test_v2_rejects_wrong_or_unknown_first_observed_step(self):
        task = sample_task()
        wrong = sample_review_v2()
        wrong["episodes"][0]["first_observed_step_id"] = "s2"
        with self.assertRaisesRegex(ValueError, "earliest onset"):
            run.validate_review(wrong, task, {"proposals": []})

        unknown = sample_review_v2()
        unknown["episodes"][0]["first_observed_step_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "Unknown first_observed_step_id"):
            run.validate_review(unknown, task, {"proposals": []})

    def test_v2_rejects_duplicate_refs_and_inconsistent_step_episode_links(self):
        task = sample_task()
        cases = []

        duplicate_episode_ref = sample_review_v2()
        duplicate_episode_ref["steps"][0]["episode_refs"] = ["e1", "e1"]
        cases.append(("duplicate episode refs", duplicate_episode_ref, "Duplicate reference"))

        duplicate_onset = sample_review_v2()
        duplicate_onset["episodes"][0]["onset_step_ids"] = ["s1", "s1"]
        cases.append(("duplicate onset refs", duplicate_onset, "Duplicate reference"))

        missing_onset_link = sample_review_v2()
        missing_onset_link["steps"][0]["episode_refs"] = []
        cases.append(("missing onset link", missing_onset_link, "missing onset/recovery tags"))

        missing_recovery_link = sample_review_v2()
        missing_recovery_link["episodes"][0]["recovery"].update(
            status="recovered", step_ids=["s2"], evidence_refs=["event-2"]
        )
        cases.append(("missing recovery link", missing_recovery_link, "missing onset/recovery tags"))

        unknown_episode_ref = sample_review_v2()
        unknown_episode_ref["steps"][1]["episode_refs"] = ["missing-episode"]
        cases.append(("unknown episode link", unknown_episode_ref, "Invalid step evidence/episode reference"))

        for case, review, message in cases:
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, message):
                run.validate_review(review, task, {"proposals": []})

    def test_saved_unversioned_reviews_still_validate(self):
        run_ids = ("20260926-224411-20aa4", "20260926-225934-c522c")
        available = [run_id for run_id in run_ids if (POC_DIR / "runs" / run_id / "run.json").is_file()]
        if not available:
            self.skipTest("Saved legacy POC runs are not present in this checkout")

        for run_id in available:
            with self.subTest(run_id=run_id):
                run_dir = POC_DIR / "runs" / run_id
                manifest = json.loads((run_dir / "run.json").read_text())
                self.assertEqual(len(manifest["tasks"]), 5)
                for saved_task in manifest["tasks"]:
                    with self.subTest(task_id=saved_task["task_id"]):
                        task_path = run_dir / saved_task["task_id"] / "input.json"
                        task = json.loads(task_path.read_text())
                        review = saved_task["review"]
                        self.assertNotIn("schema_version", review)
                        run.validate_review(review, task, manifest["taxonomy"])


class DedupContractTests(unittest.TestCase):
    def setUp(self):
        self.pool = {"proposals": [{"id": "p001"}, {"id": "p002"}]}

    @staticmethod
    def candidate():
        return {
            "summary": "The proposals describe the same mechanism.",
            "labels": [
                {
                    "id": "label-1",
                    "name": "Unconfirmed action",
                    "description": "The action was not verified.",
                    "aliases": [],
                    "status": "draft",
                }
            ],
            "mappings": [
                {"proposal_id": "p001", "canonical_label_id": "label-1", "rationale": "Same mechanism."},
                {"proposal_id": "p002", "canonical_label_id": "label-1", "rationale": "Same mechanism."},
            ],
            "unresolved": [],
        }

    def test_accepts_total_mapping_of_multiple_proposals_to_one_canonical_label(self):
        run.validate_dedup(self.candidate(), self.pool)

    def test_rejects_missing_duplicate_and_unknown_mappings(self):
        missing = self.candidate()
        missing["mappings"].pop()

        duplicate = self.candidate()
        duplicate["mappings"][1]["proposal_id"] = "p001"

        unknown_canonical = self.candidate()
        unknown_canonical["mappings"][0]["canonical_label_id"] = "missing-label"

        orphan_label = self.candidate()
        orphan_label["labels"].append(
            {
                "id": "orphan-label",
                "name": "Unmapped mechanism",
                "description": "No proposal supports this label.",
                "aliases": [],
                "status": "draft",
            }
        )

        for case, result in (
            ("missing proposal", missing),
            ("duplicate proposal", duplicate),
            ("unknown canonical", unknown_canonical),
            ("orphan canonical", orphan_label),
        ):
            with self.subTest(case=case), self.assertRaises(ValueError):
                run.validate_dedup(result, self.pool)


class SharedProposalPoolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "labels.sqlite"
        db = label_tools.connect(self.db_path)
        db.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def proposal_args(name, base_version="v0"):
        return {
            "name": name,
            "description": f"Description for {name}.",
            "episode_id": "episode-1",
            "type": "new",
            "target_label_id": "",
            "base_version": base_version,
            "evidence_refs": ["event-1"],
        }

    @staticmethod
    def task(task_id):
        return {"task_id": task_id, "steps": [{"evidence_refs": ["event-1"]}]}

    def test_concurrent_appends_preserve_both_and_mark_stale_base(self):
        start = threading.Barrier(2)

        def append(task_id, name):
            db = label_tools.connect(self.db_path)
            try:
                start.wait(timeout=5)
                return label_tools.propose(db, self.task(task_id), self.proposal_args(name))
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: append(*pair), [("task-a", "Label A"), ("task-b", "Label B")]))

        db = label_tools.connect(self.db_path)
        try:
            shared = label_tools.snapshot(db)
        finally:
            db.close()

        self.assertEqual(shared["pool_version"], "v2")
        self.assertEqual({item["name"] for item in shared["proposals"]}, {"Label A", "Label B"})
        self.assertEqual({result["proposal"]["status"] for result in results}, {"draft", "stale_base"})

    def test_duplicate_append_is_idempotent(self):
        db = label_tools.connect(self.db_path)
        try:
            first = label_tools.propose(db, self.task("task-a"), self.proposal_args("Same label"))
            second = label_tools.propose(db, self.task("task-a"), self.proposal_args("Same label"))
            shared = label_tools.snapshot(db)
        finally:
            db.close()

        self.assertEqual(first["proposal"]["id"], second["proposal"]["id"])
        self.assertEqual(shared["pool_version"], "v1")
        self.assertEqual(len(shared["proposals"]), 1)

    def test_stdio_tool_schema_constrains_proposal_type(self):
        task_path = Path(self.temp_dir.name) / "task.json"
        task_path.write_text(json.dumps(self.task("task-a")))
        request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        response = subprocess.run(
            [
                sys.executable,
                str(POC_DIR / "label_tools.py"),
                "--db",
                str(self.db_path),
                "--task",
                str(task_path),
            ],
            input=request + "\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        tools = json.loads(response.stdout.strip())["result"]["tools"]
        propose_label = next(tool for tool in tools if tool["name"] == "propose_label")

        type_property = propose_label["inputSchema"]["properties"]["type"]
        self.assertEqual(type_property["type"], "string")
        self.assertEqual(type_property["enum"], ["new", "update"])


if __name__ == "__main__":
    unittest.main()
