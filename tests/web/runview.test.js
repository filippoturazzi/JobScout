import { test } from "node:test";
import assert from "node:assert/strict";

const { runView, shouldKeepPolling, matchChanged } = await import("../../src/jobscout/web/js/runview.js");

const search = { id: 7 };
const src = (name, state, extra = {}) => ({ name, state, fetched: 0, queries_done: 0, queries_total: 0, detail: null, ...extra });
const run = (extra = {}) => ({
  id: 3,
  search_id: 7,
  started_at: "2026-11-08T10:00:00",
  finished_at: "2026-11-08T10:05:00",
  ok: true,
  error: null,
  counters: { fetched: 31, scored: 12, to_score: 40 },
  sources: [src("himalayas", "done", { fetched: 23 }), src("remotive", "done", { fetched: 8 })],
  ...extra,
});
const match = (id, score) => ({ id, score, job: { id } });
const list = (found, waiting, matches = []) => ({ matches, found, waiting });

test("runView: no run is none", () => {
  assert.equal(runView(search, null, null, null).state, "none");
});

test("runView: unfinished and running here is running", () => {
  const v = runView(search, run({ finished_at: null }), list(0, 0), 7);
  assert.equal(v.state, "running");
  assert.deepEqual(v.progress, { sources: 2, scored: 12, toScore: 40 });
});

test("runView: unfinished but not running is interrupted", () => {
  assert.equal(runView(search, run({ finished_at: null }), list(3, 0), null).state, "interrupted");
  assert.equal(runView(search, run({ finished_at: null }), list(3, 0), 9).state, "interrupted");
});

test("runView: results, waiting only and nothing", () => {
  assert.equal(runView(search, run(), list(12, 9), null).state, "results");
  assert.equal(runView(search, run(), list(0, 9), null).state, "waiting_only");
  assert.equal(runView(search, run(), list(0, 0), null).state, "nothing");
  // A finished run is never running, whatever /status says.
  assert.equal(runView(search, run(), list(0, 0), 7).state, "nothing");
});

test("runView: cards are ordered by score, unscored last", () => {
  const v = runView(search, run({ finished_at: null }), list(3, 0, [match(1, 60), match(2, null), match(3, 91)]), 7);
  assert.deepEqual(v.matches.map((m) => m.id), [3, 1, 2]);
});

test("runView: failed and skipped sources become failures", () => {
  const r = run({
    sources: [
      src("himalayas", "done", { fetched: 23 }),
      src("linkedin", "failed", { detail: "too many requests" }),
      src("indeed", "skipped", { detail: "not searched, it only lists remote jobs" }),
      src("remotive", "done", { fetched: 4, detail: "HTTP 500" }),
      src("arbeitnow", "waiting"),
    ],
  });
  const v = runView(search, r, list(0, 0), null);
  assert.deepEqual(v.failures, [
    { name: "linkedin", kind: "failed", detail: "too many requests" },
    { name: "indeed", kind: "skipped", detail: "not searched, it only lists remote jobs" },
    { name: "remotive", kind: "failed", detail: "HTTP 500" },
  ]);
  assert.equal(v.fetched, 31);
});

test("runView: a finished run that failed names its error, cut short", () => {
  assert.equal(runView(search, run(), list(0, 0), null).runError, null);
  assert.equal(runView(search, run({ ok: false, error: "boom" }), list(0, 9), null).runError, "boom");
  const long = runView(search, run({ ok: false, error: "x".repeat(500) }), list(0, 0), null).runError;
  assert.equal(long.length, 201);
  assert.ok(long.endsWith("…"));
  // Still in flight: not a failure yet.
  assert.equal(runView(search, run({ finished_at: null, ok: false, error: null }), list(0, 0), 7).runError, null);
});

test("polling stops once a restart leaves the run unfinished and /status no longer runs it", () => {
  const unfinished = run({ finished_at: null });
  assert.equal(shouldKeepPolling(runView(search, unfinished, list(0, 0), 7)), true);
  // Same run, still unfinished, but the fresh /status says nothing runs: interrupted.
  const after = runView(search, unfinished, list(0, 0), null);
  assert.equal(after.state, "interrupted");
  assert.equal(shouldKeepPolling(after), false);
  assert.equal(shouldKeepPolling(runView(search, run(), list(2, 0), 7)), false);
});

test("matchChanged notices a new score, reasoning or status only", () => {
  const a = { id: 1, score: 80, reasoning: "ok", status: "new", matched_skills: ["Python"], missing_skills: [], red_flags: [], job: { id: 1 } };
  assert.equal(matchChanged(a, { ...a, job: { id: 1, title: "x" } }), false);
  assert.equal(matchChanged(a, { ...a, score: 81 }), true);
  assert.equal(matchChanged(a, { ...a, status: "saved" }), true);
  assert.equal(matchChanged(a, { ...a, matched_skills: ["Python", "RAG"] }), true);
});

test("runView: searched counts the sources that were not skipped", () => {
  const sources = [src("himalayas", "done"), src("remotive", "done"), src("linkedin", "failed"), src("indeed", "skipped")];
  assert.equal(runView(search, run({ sources }), list(0, 0), null).searched, 3);
  assert.equal(runView(search, run({ sources: [], counters: { sources_ok: 2, sources_failed: 1 } }), list(0, 0), null).searched, 3);
});
