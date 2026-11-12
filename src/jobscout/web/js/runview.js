// What a search's run area shows, from the search, its latest run and its matches. Pure.
//
// state: none (no run) · running (unfinished and this search is the one in flight) ·
// interrupted (unfinished, but nothing runs it any more: a restart) · results (something
// scored, or jobs with no score to list after it) · nothing.

const ERROR_LENGTH = 200;

const byScore = (a, b) => (typeof b.score === "number" ? b.score : -1) - (typeof a.score === "number" ? a.score : -1);

// While a run is in flight its cards are the ones it scored: a score from before it started
// (a previous run's, or a stale one waiting to be redone) would read as a fresh result.
// Both timestamps are naive UTC from the API, so they compare as they are.
function scoredBy(run) {
  const started = Date.parse(run.started_at);
  return (m) => {
    if (m.status === "stale") return false;
    const updated = Date.parse(m.updated_at);
    return Number.isNaN(started) || Number.isNaN(updated) || updated >= started;
  };
}

export function runView(search, run, matchList, runningSearchId) {
  const list = matchList || { matches: [], found: 0, waiting: 0, unscored: [] };
  const found = list.found || 0;
  const waiting = list.waiting || 0;
  const unscored = list.unscored || [];
  const sources = (run && run.sources) || [];
  const counters = (run && run.counters) || {};

  let state;
  if (!run) state = "none";
  else if (!run.finished_at) state = runningSearchId === search.id ? "running" : "interrupted";
  else if (found > 0 || unscored.length > 0) state = "results";
  else state = "nothing";

  // A source that answered and then failed stays "done" but carries why in `detail`. Its notes
  // (a country past the budget, a region it could not map) follow it, one line each.
  const failures = [];
  for (const s of sources) {
    if (s.state === "failed" || s.state === "skipped" || (s.state === "done" && s.detail)) {
      failures.push({ name: s.name, kind: s.state === "skipped" ? "skipped" : "failed", detail: s.detail || "" });
    }
    for (const note of s.notes || []) failures.push({ name: s.name, kind: "note", detail: note });
  }

  // A run that ended with an error says so, cut to a readable length (provider errors are long).
  // The run's error joins every source's message with "; ": the ones a line above already
  // names are left out, so a run where every source failed does not say it all twice.
  let runError = null;
  if (run && run.finished_at && !run.ok && run.error) {
    const named = new Set(failures.map((f) => `${f.name}: ${f.detail}`));
    const rest = run.error.split("; ").filter((part) => !named.has(part)).join("; ");
    if (rest) runError = rest.length > ERROR_LENGTH ? `${rest.slice(0, ERROR_LENGTH)}…` : rest;
  }

  // Sources the run actually searched: not the skipped ones.
  const searched = sources.length ? sources.filter((s) => s.state !== "skipped").length : (counters.sources_ok || 0) + (counters.sources_failed || 0);

  return {
    state,
    searched,
    runError,
    found,
    waiting,
    // While a run is in flight the unscored list grows on every poll: it shows once it ends.
    unscored: state === "running" ? [] : unscored,
    // Nothing scored and nothing left to score: only jobs the prefilter turned away.
    widen: found === 0 && waiting === 0,
    fetched: counters.fetched || 0,
    sources,
    // A ranking run never touches the sources: they all stay "waiting".
    searchedSources: sources.some((s) => s.state !== "waiting"),
    failures,
    progress: { sources: sources.length, scored: counters.scored || 0, toScore: counters.to_score || 0 },
    matches: (list.matches || []).filter(state === "running" ? scoredBy(run) : () => true).sort(byScore),
  };
}

// The line over a running search. A run with no sources yet (the placeholder a start draws
// before the first poll, or a reloaded ranking run) says "Searching…", never "0 sources".
export function runHeadline(view, ranking) {
  // A ranking run calls no source, so its source lines would all say "waiting".
  const searching = !ranking && (view.searchedSources || view.progress.toScore === 0);
  if (!searching) return { key: "ranking", showSources: false };
  if (!view.progress.sources) return { key: "searching", showSources: false };
  return { key: "searching_sources", n: view.progress.sources, showSources: true };
}

// Polling runs only while the run is in flight here; an interrupted run stops it.
export function shouldKeepPolling(view) {
  return view.state === "running";
}

// The polled match for what the detail panel shows: by match id, or, for a job that had no
// score when it was opened, the match a ranking has since given that job.
export function freshFor(list, current) {
  const matches = (list && list.matches) || [];
  const unscored = current.id === null || current.id === undefined;
  return matches.find((m) => (unscored ? m.job && m.job.id === current.job.id : m.id === current.id)) || null;
}

// Whether a polled match differs from the one shown in the detail panel.
export function matchChanged(a, b) {
  if (!a || !b) return Boolean(a) !== Boolean(b);
  const keys = ["score", "reasoning", "status", "matched_skills", "missing_skills", "red_flags"];
  return keys.some((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]));
}

// A search's results after a verdict on one of them: dismissed and applied leave the list,
// any other status stays (or comes back, when a verdict was taken back) in score order.
export function withVerdict(list, updated) {
  const rest = list.matches.filter((m) => m.id !== updated.id);
  const wasListed = rest.length !== list.matches.length;
  if (updated.status === "dismissed" || updated.status === "applied") {
    return wasListed ? { ...list, matches: rest, found: Math.max(list.found - 1, 0) } : list;
  }
  if (wasListed) return { ...list, matches: list.matches.map((m) => (m.id === updated.id ? updated : m)) };
  const score = (m) => (m.score === null || m.score === undefined ? -1 : m.score);
  const at = rest.findIndex((m) => score(m) < score(updated));
  const matches = at === -1 ? [...rest, updated] : [...rest.slice(0, at), updated, ...rest.slice(at)];
  return { ...list, matches, found: list.found + 1 };
}
