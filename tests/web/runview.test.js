import { test } from "node:test";
import assert from "node:assert/strict";

const { runView, runHeadline, shouldKeepPolling, matchChanged, freshFor } = await import("../../src/jobscout/web/js/runview.js");

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
const list = (found, waiting, matches = [], unscored = []) => ({ matches, found, waiting, unscored });
const loose = (n) => Array.from({ length: n }, (_, i) => ({ job: { id: 100 + i }, similarity: null, match_id: null }));

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
  assert.equal(runView(search, run(), list(0, 9, [], loose(9)), null).state, "results");
  assert.equal(runView(search, run(), list(0, 0), null).state, "nothing");
  // A finished run is never running, whatever /status says.
  assert.equal(runView(search, run(), list(0, 0), 7).state, "nothing");
});

test("runView: a running search shows only what this run scored, not the last run's scores", () => {
  const m = (id, status, updated_at) => ({ id, score: 60, status, updated_at });
  const matches = [
    m(1, "stale", "2026-10-27T13:23:27"), // an old score waiting to be re-evaluated
    m(2, "new", "2026-10-27T13:20:00"), // a previous run's result
    m(3, "new", "2026-11-08T10:01:00"), // scored by this run (it started at 10:00)
    m(4, "saved", "2026-11-08T10:02:00"), // this run's result the user already saved
  ];
  const running = runView(search, run({ finished_at: null }), list(4, 0, matches), 7);
  assert.deepEqual(running.matches.map((x) => x.id), [3, 4]);
  // Once the run ends, the results are every score the search has.
  assert.equal(runView(search, run(), list(4, 0, matches), null).matches.length, 4);
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

test("runView: a source's notes become lines of their own, after its failure", () => {
  const r = run({
    sources: [
      src("indeed", "done", { fetched: 4, notes: ["not searched in Spain, only 2 searches per run"] }),
      src("linkedin", "failed", { detail: "too many requests", notes: ["could not map region 'remoto'"] }),
      src("himalayas", "done"),
    ],
  });
  assert.deepEqual(runView(search, r, list(1, 0), null).failures, [
    { name: "indeed", kind: "note", detail: "not searched in Spain, only 2 searches per run" },
    { name: "linkedin", kind: "failed", detail: "too many requests" },
    { name: "linkedin", kind: "note", detail: "could not map region 'remoto'" },
  ]);
  // A row from before notes existed has none.
  assert.deepEqual(runView(search, run(), list(1, 0), null).failures, []);
});

test("runView: the run error leaves out what a source line already says", () => {
  const sources = [
    src("linkedin", "failed", { detail: "SourceBlocked: 429" }),
    src("indeed", "failed", { detail: "HTTP 500", notes: ["not searched in Spain, only 2 searches per run"] }),
  ];
  const every = run({ ok: false, sources, error: "linkedin: SourceBlocked: 429; indeed: not searched in Spain, only 2 searches per run; indeed: HTTP 500" });
  assert.equal(runView(search, every, list(0, 0), null).runError, null);
  const more = run({ ok: false, sources, error: "linkedin: SourceBlocked: 429; ValueError: scoring broke" });
  assert.equal(runView(search, more, list(0, 0), null).runError, "ValueError: scoring broke");
});

test("runHeadline: a run with no sources yet never says it searches 0 of them", () => {
  const running = (extra) => runView(search, run({ finished_at: null, ...extra }), list(0, 0), 7);
  // The placeholder run a start draws before the first poll, and a reloaded ranking run.
  assert.deepEqual(runHeadline(running({ sources: [], counters: {} }), false), { key: "searching", showSources: false });
  const two = running({ sources: [src("himalayas", "searching"), src("remotive", "waiting")], counters: {} });
  assert.deepEqual(runHeadline(two, false), { key: "searching_sources", n: 2, showSources: true });
  // A ranking run calls no source.
  assert.deepEqual(runHeadline(two, true), { key: "ranking", showSources: false });
  const ranked = running({ sources: [], counters: { to_score: 5, scored: 1 } });
  assert.deepEqual(runHeadline(ranked, false), { key: "ranking", showSources: false });
});

test("a verdict that closes a job takes it out of the results; taking it back puts it back in score order", async () => {
  const { withVerdict } = await import("../../src/jobscout/web/js/runview.js");
  const m = (id, score, status = "new") => ({ id, score, status });
  const list = { found: 3, matches: [m(1, 90), m(2, 70), m(3, 50)] };

  const dismissed = withVerdict(list, m(2, 70, "dismissed"));
  assert.deepEqual(dismissed.matches.map((x) => x.id), [1, 3]);
  assert.equal(dismissed.found, 2);

  const back = withVerdict(dismissed, m(2, 70, "new"));
  assert.deepEqual(back.matches.map((x) => x.id), [1, 2, 3]);
  assert.equal(back.found, 3);

  const saved = withVerdict(back, m(2, 70, "saved"));
  assert.deepEqual(saved.matches.map((x) => [x.id, x.status]), [[1, "new"], [2, "saved"], [3, "new"]]);
  assert.equal(saved.found, 3);
});

test("runView: unscored jobs alone are results, with the widenings when none can be scored", () => {
  const v = runView(search, run(), list(0, 0, [], loose(2)), null);
  assert.equal(v.state, "results");
  assert.equal(v.widen, true);
  assert.equal(v.unscored.length, 2);
});

test("runView: no widenings once something is scored or can still be", () => {
  assert.equal(runView(search, run(), list(3, 4, [match(1, 80)], loose(4)), null).widen, false);
  assert.equal(runView(search, run(), list(0, 4, [], loose(4)), null).widen, false);
});

test("runView: nothing scored and nothing unscored is nothing", () => {
  assert.equal(runView(search, run(), list(0, 0, [], []), null).state, "nothing");
});

test("runView: a running search shows no unscored jobs", () => {
  const v = runView(search, run({ finished_at: null }), list(0, 3, [], loose(3)), 7);
  assert.equal(v.state, "running");
  assert.deepEqual(v.unscored, []);
});

test("runView: a payload without unscored reads as none", () => {
  const v = runView(search, run(), { matches: [match(1, 80)], found: 1, waiting: 0 }, null);
  assert.deepEqual(v.unscored, []);
  assert.equal(v.state, "results");
});

test("freshFor: a panel finds its match again by id", () => {
  const list = { matches: [match(5, 70), match(6, 80)] };
  assert.equal(freshFor(list, match(6, 50)).score, 80);
  assert.equal(freshFor(list, match(9, 50)), null);
});

test("freshFor: an unscored job open in the panel finds the match a ranking gave it", () => {
  const scored = { id: 12, score: 81, job: { id: 300 } };
  const open = { id: null, score: null, job: { id: 300 }, unscored: true };
  assert.equal(freshFor({ matches: [match(5, 70), scored] }, open), scored);
  assert.equal(freshFor({ matches: [match(5, 70)] }, open), null);
});
