import { test } from "node:test";
import assert from "node:assert/strict";

const { runningMismatch, shouldWatch } = await import("../../src/jobscout/web/js/store.js");

const searches = (...running) => [1, 2, 3].map((id) => ({ id, title: `s${id}`, running: running.includes(id) }));
const status = (id) => ({ running_search_id: id });

test("shouldWatch: only while something runs", () => {
  assert.equal(shouldWatch(status(null), searches()), false);
  assert.equal(shouldWatch(null, []), false);
  assert.equal(shouldWatch(status(2), searches()), true);
  // The run ended but the sidebar still marks it: keep going until the list catches up.
  assert.equal(shouldWatch(status(null), searches(2)), true);
});

test("runningMismatch: the status and the sidebar's running flags disagree", () => {
  assert.equal(runningMismatch(status(null), searches()), false);
  assert.equal(runningMismatch(status(2), searches(2)), false);
  assert.equal(runningMismatch(status(null), searches(2)), true);
  assert.equal(runningMismatch(status(2), searches()), true);
  assert.equal(runningMismatch(status(3), searches(2)), true);
  // A running search the list does not have (just deleted, say) cannot be marked: no refresh loop.
  assert.equal(runningMismatch(status(9), searches()), false);
  assert.equal(runningMismatch(null, searches()), false);
});
