// My jobs' view as data: what it asks GET /my-jobs, how many filters are on, the chips that
// show them, and the page in hand. The view is the route's (router.js). All pure.

export const PAGE_SIZE = 20;

export function apiQuery(view) {
  const q = new URLSearchParams({ tab: view.tab });
  if (view.search) q.set("search_id", String(view.search));
  if (view.min) q.set("min_score", String(view.min));
  view.modes.forEach((m) => q.append("mode", m));
  view.sources.forEach((s) => q.append("source", s));
  if (view.since) q.set("since", view.since);
  if (view.q) q.set("q", view.q);
  q.set("sort", view.sort);
  q.set("offset", String((view.page - 1) * PAGE_SIZE));
  q.set("limit", String(PAGE_SIZE));
  return q.toString();
}

// The filters of the popover; the tab, the search, the text and the sort are not counted.
export function filterCount(view) {
  return (view.min ? 1 : 0) + view.modes.length + view.sources.length + (view.since ? 1 : 0);
}

export function clearFilters(view) {
  return { ...view, min: 0, modes: [], sources: [], since: null, page: 1 };
}

// One chip per filter on, each with the view that takes it off (back on the first page).
export function filterChips(view) {
  const off = (change) => ({ ...view, ...change, page: 1 });
  const chips = [];
  if (view.min) chips.push({ key: "min", kind: "min", value: view.min, without: off({ min: 0 }) });
  view.modes.forEach((m) => chips.push({ key: `mode:${m}`, kind: "mode", value: m, without: off({ modes: view.modes.filter((x) => x !== m) }) }));
  view.sources.forEach((s) => chips.push({ key: `source:${s}`, kind: "source", value: s, without: off({ sources: view.sources.filter((x) => x !== s) }) }));
  if (view.since) chips.push({ key: "since", kind: "since", value: view.since, without: off({ since: null }) });
  return chips;
}

export function pageInfo(page, total) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const from = total ? (page - 1) * PAGE_SIZE + 1 : 0;
  return { from, to: Math.min(total, page * PAGE_SIZE), pages, prev: page > 1, next: page < pages };
}
