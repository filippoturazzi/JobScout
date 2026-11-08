// What a search's run area shows, from the search, its latest run and its matches. Pure.
//
// state: none (no run) · running (unfinished and this search is the one in flight) ·
// interrupted (unfinished, but nothing runs it any more: a restart) · results (found > 0) ·
// waiting_only (nothing found, jobs waiting for a score) · nothing.

const ERROR_LENGTH = 200;

const byScore = (a, b) => (typeof b.score === "number" ? b.score : -1) - (typeof a.score === "number" ? a.score : -1);

export function runView(search, run, matchList, runningSearchId) {
  const list = matchList || { matches: [], found: 0, waiting: 0 };
  const found = list.found || 0;
  const waiting = list.waiting || 0;
  const sources = (run && run.sources) || [];
  const counters = (run && run.counters) || {};

  let state;
  if (!run) state = "none";
  else if (!run.finished_at) state = runningSearchId === search.id ? "running" : "interrupted";
  else if (found > 0) state = "results";
  else if (waiting > 0) state = "waiting_only";
  else state = "nothing";

  // A source that answered and then failed stays "done" but carries why in `detail`.
  const failures = sources
    .filter((s) => s.state === "failed" || s.state === "skipped" || (s.state === "done" && s.detail))
    .map((s) => ({ name: s.name, kind: s.state === "skipped" ? "skipped" : "failed", detail: s.detail || "" }));

  // A run that ended with an error says so, cut to a readable length (provider errors are long).
  let runError = null;
  if (run && run.finished_at && !run.ok && run.error) {
    runError = run.error.length > ERROR_LENGTH ? `${run.error.slice(0, ERROR_LENGTH)}…` : run.error;
  }

  return {
    state,
    runError,
    found,
    waiting,
    fetched: counters.fetched || 0,
    sources,
    // A ranking run never touches the sources: they all stay "waiting".
    searchedSources: sources.some((s) => s.state !== "waiting"),
    failures,
    progress: { sources: sources.length, scored: counters.scored || 0, toScore: counters.to_score || 0 },
    matches: [...(list.matches || [])].sort(byScore),
  };
}

// Polling runs only while the run is in flight here; an interrupted run stops it.
export function shouldKeepPolling(view) {
  return view.state === "running";
}

// Whether a polled match differs from the one shown in the detail panel.
export function matchChanged(a, b) {
  if (!a || !b) return Boolean(a) !== Boolean(b);
  const keys = ["score", "reasoning", "status", "matched_skills", "missing_skills", "red_flags"];
  return keys.some((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
}
