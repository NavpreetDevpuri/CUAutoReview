import assert from "node:assert/strict";
import test from "node:test";
import { groupStepFlags, stepFlagEvidence } from "../src/stepFlagGroups.ts";

test("matching display text retains every review occurrence and local problem number", () => {
  const first = Object.freeze({ kind: "problem", label: "Wrong target", relation: "Continues from step 2", number: "1", review: "1", model: "model-a", run: "First run" });
  const second = Object.freeze({ ...first, number: "3", review: "2", model: "model-b", run: "Second run" });
  const flags = Object.freeze([first, second, first]);
  const groups = groupStepFlags(flags);
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0].flags, [first, second, first]);
  assert.equal(groups[0].flags[1], second);
  assert.equal(flags.length, 3);
});

test("different kind, exact label or step relation stay separate and in first-seen order", () => {
  const first = { kind: "problem", label: "Wrong target", relation: "Continues from step 2" };
  const variants = [
    first,
    { ...first, kind: "recovery" },
    { ...first, label: "Wrong Target" },
    { ...first, relation: "Continues from step 3" },
  ];
  const groups = groupStepFlags([...variants, { ...first }]);
  assert.equal(groups.length, 4);
  assert.deepEqual(groups.map(group => group.flags[0]), variants);
  assert.deepEqual(groups.map(group => group.flags.length), [2, 1, 1, 1]);
  assert.deepEqual(groupStepFlags([]), []);
});

test("source presence and model citations never imply frame delivery", () => {
  assert.equal(stepFlagEvidence({}, "2"), "Delivery unknown");
  assert.equal(stepFlagEvidence({ source_image_step_ids: [2], cited_image_step_ids: [2] }, "2"), "Delivery unknown · frame cited");
  assert.equal(stepFlagEvidence({ source_image_step_ids: [2], supplied_image_step_ids: [], cited_image_step_ids: [] }, "2"), "Frame not sent · not cited");
  assert.equal(stepFlagEvidence({ source_image_step_ids: [2], supplied_image_step_ids: [2], cited_image_step_ids: [] }, "2"), "Frame sent · not cited");
  assert.equal(stepFlagEvidence({ evidence_mode: "text_only" }, "2"), "Frame not sent · text-only review");
  assert.equal(stepFlagEvidence({ inspected_image_step_ids: [] }, "2"), "Frame not sent · legacy text-only review");
  assert.equal(stepFlagEvidence({ inspected_image_step_ids: [], supplied_image_step_ids: [2] }, "2"), "Frame sent");
  assert.equal(stepFlagEvidence({ source_image_step_ids: [] }, "2"), "Delivery unknown · no source frame listed");
});
