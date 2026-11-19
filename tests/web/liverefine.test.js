import { test } from "node:test";
import assert from "node:assert/strict";

const { nextStep } = await import("../../src/jobscout/web/js/liverefine.js");

const q = { id: "city" };
const step = (over) => nextStep({ hasRun: true, running: false, queued: false, question: null, ...over });

test("before the first search nothing runs by itself", () => {
  assert.equal(step({ hasRun: false }), "none");
  assert.equal(step({ hasRun: false, question: q }), "none");
});

test("a pending question is asked first", () => {
  assert.equal(step({ question: q }), "ask");
  assert.equal(step({ question: q, running: true }), "ask");
});

test("a run in flight is stopped once, then waited for", () => {
  assert.equal(step({ running: true }), "stop");
  assert.equal(step({ running: true, queued: true }), "wait");
});

test("with nothing running and nothing pending, it runs", () => {
  assert.equal(step({}), "run");
});

test("a queued run starts once the question is answered and nothing runs", () => {
  assert.equal(step({ queued: true }), "run");
});
