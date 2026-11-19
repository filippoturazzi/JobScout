// What follows a refinement or an edit. Pure. After the first search, a change updates the
// results by itself: a pending question is asked first, a run in flight is stopped once and
// waited for (queued), and only then does a new run start, so two never pile up.
//
// none: before the first search, the summary just updates · ask: a question came up, the run
// waits for its answer · stop: post the stop and queue · wait: the stop is already asked ·
// run: start the run now.
export function nextStep({ hasRun, running, queued, question }) {
  if (!hasRun) return "none";
  if (question) return "ask";
  if (running) return queued ? "wait" : "stop";
  return "run";
}
