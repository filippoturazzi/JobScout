// Shared state: the server's /status and the list of searches.
import { api } from "./api.js";

export const state = { status: null, searches: [] };
const listeners = new Set();
// Searches deleted with Undo still on offer: the server has them until the toast goes.
const hidden = new Set();

function notify() {
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// silent: update the status without redrawing the app (a run's polling reads it itself).
export async function refreshStatus({ silent = false } = {}) {
  state.status = await api.get("/status");
  if (!silent) notify();
  return state.status;
}

// silent: update the list without notifying; the caller redraws what needs it (the sidebar).
export async function refreshSearches({ silent = false } = {}) {
  state.searches = withoutHidden(await api.get("/searches"), hidden);
  if (!silent) notify();
  return state.searches;
}

// The list minus the searches waiting to be deleted. Pure.
export function withoutHidden(searches, ids) {
  return (searches || []).filter((s) => !ids.has(s.id));
}

export function hideSearch(id) {
  hidden.add(id);
  state.searches = withoutHidden(state.searches, hidden);
  notify();
}

export function unhideSearch(id) {
  hidden.delete(id);
}

// Whether something runs, by /status or by the sidebar's own markers (a run that just ended
// is still marked until the list is read again). Pure.
export function shouldWatch(status, searches) {
  const id = status ? status.running_search_id : null;
  return (id !== null && id !== undefined) || (searches || []).some((s) => s.running);
}

// Whether /status and the list's running flags disagree, so the list needs reading again.
// A running id the list does not hold cannot be marked, so it is no disagreement. Pure.
export function runningMismatch(status, searches) {
  const list = searches || [];
  const id = status ? status.running_search_id : null;
  const marked = list.filter((s) => s.running).map((s) => s.id);
  const expected = id !== null && id !== undefined && list.some((s) => s.id === id) ? [id] : [];
  return marked.length !== expected.length || marked.some((m) => !expected.includes(m));
}
