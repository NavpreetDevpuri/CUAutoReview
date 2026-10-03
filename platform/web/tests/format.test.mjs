import assert from "node:assert/strict";
import test from "node:test";
import { countLabel, displayValue, formatDate, reviewProcessingError, runStatusLabel } from "../src/lib/format.ts";
import { asRecord } from "../src/lib/records.ts";

test("counts use singular and plural nouns", () => {
  assert.equal(countLabel(1, "task"), "1 task");
  assert.equal(countLabel(3, "task"), "3 tasks");
  assert.equal(countLabel(2, "copy", "copies"), "2 copies");
});

test("a completed run with failed tasks is labelled as finished with errors", () => {
  assert.equal(runStatusLabel({ status: "completed", progress: { failed: 2 } }), "finished with errors");
  assert.equal(runStatusLabel({ status: "completed", failed_task_count: 0 }), "completed");
  assert.equal(runStatusLabel({ status: "running", archived_at: "2026-10-01" }), "archived");
  assert.equal(runStatusLabel({}), "unknown");
});

test("missing values read as not recorded instead of zero or empty", () => {
  assert.equal(displayValue(null), "Not recorded");
  assert.equal(displayValue(""), "Not recorded");
  assert.equal(displayValue(0), "0");
  assert.equal(displayValue(false), "false");
  assert.equal(displayValue({ a: 1 }), '{\n  "a": 1\n}');
  assert.equal(formatDate(undefined), "Not recorded");
  assert.equal(formatDate("not a date"), "not a date");
});

test("structured-output failures are explained as review-processing errors", () => {
  const message = reviewProcessingError("Gemini CLI returned invalid JSON. No retry was made.");
  assert.match(message, /review-processing error/);
  assert.match(message, /No automatic retry was made\./);
  assert.equal(reviewProcessingError("Provider quota exceeded"), "Provider quota exceeded");
  assert.equal(reviewProcessingError(undefined), "No error reason recorded");
});

test("only plain objects pass through asRecord", () => {
  assert.deepEqual(asRecord({ id: "a" }), { id: "a" });
  assert.deepEqual(asRecord(["a"]), {});
  assert.deepEqual(asRecord("a"), {});
  assert.deepEqual(asRecord(null), {});
});
