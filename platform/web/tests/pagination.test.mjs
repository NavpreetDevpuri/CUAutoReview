import assert from "node:assert/strict";
import test from "node:test";
import { collectPages, pageItems, withPageParams } from "../src/api/pagination.ts";
import { endsSession } from "../src/api/sessionErrors.ts";

test("page parameters are added without dropping existing filters", () => {
  assert.equal(withPageParams("/runs/r1/tasks", 2, 500), "/runs/r1/tasks?page=2&per_page=500");
  assert.equal(withPageParams("/runs?include_archived=true", 1, 200), "/runs?include_archived=true&page=1&per_page=200");
  assert.equal(withPageParams("/runs?page=9&per_page=5", 3, 200), "/runs?page=3&per_page=200");
});

test("list envelopes and bare arrays normalize to items and total", () => {
  assert.deepEqual(pageItems({ items: [1, 2], total: 7 }), { items: [1, 2], total: 7 });
  assert.deepEqual(pageItems([1, 2, 3]), { items: [1, 2, 3], total: 3 });
  assert.deepEqual(pageItems(null), { items: [], total: 0 });
  assert.deepEqual(pageItems({ items: [1], total: "bad" }), { items: [1], total: 1 });
});

test("collectPages reads every page until the reported total", async () => {
  const rows = Array.from({ length: 1201 }, (_, index) => index);
  const requested = [];
  const result = await collectPages(async page => {
    requested.push(page);
    return { items: rows.slice((page - 1) * 500, page * 500), total: rows.length };
  });
  assert.deepEqual(requested, [1, 2, 3]);
  assert.equal(result.items.length, 1201);
  assert.equal(result.items[1200], 1200);
  assert.equal(result.truncated, false);
});

test("collectPages stops at the page limit and reports truncation", async () => {
  const result = await collectPages(async page => ({ items: [page], total: 10 }), 3);
  assert.deepEqual(result.items, [1, 2, 3]);
  assert.equal(result.total, 10);
  assert.equal(result.truncated, true);
});

test("collectPages stops on an empty page even if total overstates the records", async () => {
  let calls = 0;
  const result = await collectPages(async page => { calls += 1; return { items: page === 1 ? ["a"] : [], total: 5 }; });
  assert.equal(calls, 2);
  assert.deepEqual(result.items, ["a"]);
  assert.equal(result.truncated, true);
});

test("a bare array response is a single complete page", async () => {
  let calls = 0;
  const result = await collectPages(async () => { calls += 1; return ["a", "b"]; });
  assert.equal(calls, 1);
  assert.deepEqual(result, { items: ["a", "b"], total: 2, truncated: false });
});

test("only 401 ends the session; 403 and other failures do not", () => {
  assert.equal(endsSession({ status: 401 }), true);
  assert.equal(endsSession({ status: 403 }), false);
  assert.equal(endsSession({ status: 500 }), false);
  assert.equal(endsSession(new Error("network")), false);
  assert.equal(endsSession(null), false);
});
