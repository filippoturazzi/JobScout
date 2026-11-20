// What follows a refinement or an edit. Pure. After the first search, a change updates the
// results by itself: a pending question is asked first, a run in flight (or being started) is
// stopped once and waited for, and only then does a new run start, so two never pile up.
//
// Every step but "none" and "run" leaves a run queued: the caller starts it when the question
// is answered, the stopped run ends, or the starting run has an id (and is then stopped).
// none: before the first search, the summary just updates · ask: a question came up ·
// stop: post the stop · wait: a stop is already asked, or a start is in flight · run: start now.
export function nextStep({ hasRun, running, stopping, starting, question }) {
  if (!hasRun) return "none";
  if (question) return "ask";
  if (starting) return "wait";
  if (running) return stopping ? "wait" : "stop";
  return "run";
}
