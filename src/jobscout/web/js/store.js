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

export async function refreshStatus() {
  state.status = await api.get("/status");
  notify();
  return state.status;
}

export async function refreshSearches() {
  state.searches = await api.get("/searches");
  notify();
  return state.searches;
}
