// Shared state: the server's /status and the list of searches.
import { api } from "./api.js";

export const state = { status: null, searches: [] };
const listeners = new Set();

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

export async function refreshSearches() {
  state.searches = await api.get("/searches");
  notify();
  return state.searches;
}
