// Hash routes: #/ (home), #/search/<id>, #/my-jobs[?...], #/settings. Unknown routes are home.
// My jobs keeps its whole view in the query, so a reload or a shared link shows the same list:
//   tab=saved|applied|dismissed  search=<id>  min=30|50|70  mode=remote,hybrid,onsite
//   source=<name>,...  since=24h|7d|30d  q=<text>  sort=recent|company  page=<n>
// and open=<match>: a panel to open once the list is in (the palette's saved jobs), never written.

export const MY_JOBS_TABS = ["all", "saved", "applied", "dismissed"];
export const MIN_SCORES = [0, 30, 50, 70];
export const WORK_MODES = ["remote", "hybrid", "onsite"];
export const SINCES = ["24h", "7d", "30d"];
export const SORTS = ["score", "recent", "company"];

function positive(raw) {
  const n = raw !== null && /^\d+$/.test(raw) ? Number(raw) : 0;
  return n > 0 ? n : null;
}

function list(raw, keep) {
  return (raw || "").split(",").filter((v, i, all) => keep(v) && all.indexOf(v) === i);
}

function myJobsRoute(query) {
  const params = new URLSearchParams(query);
  const pick = (name, allowed, fallback) => (allowed.includes(params.get(name)) ? params.get(name) : fallback);
  const min = Number(params.get("min"));
  return {
    name: "my-jobs",
    tab: pick("tab", MY_JOBS_TABS, "all"),
    search: positive(params.get("search")),
    open: positive(params.get("open")),
    min: MIN_SCORES.includes(min) ? min : 0,
    modes: list(params.get("mode"), (v) => WORK_MODES.includes(v)),
    sources: list(params.get("source"), (v) => /^[a-z0-9_-]+$/.test(v)),
    since: pick("since", SINCES, null),
    q: (params.get("q") || "").trim(),
    sort: pick("sort", SORTS, "score"),
    page: positive(params.get("page")) || 1,
  };
}

// The path (without "#") for a My jobs view, writing only what differs from the defaults.
export function myJobsPath(view) {
  const params = new URLSearchParams();
  if (view.tab && view.tab !== "all") params.set("tab", view.tab);
  if (view.search) params.set("search", String(view.search));
  if (view.min) params.set("min", String(view.min));
  if (view.modes && view.modes.length) params.set("mode", view.modes.join(","));
  if (view.sources && view.sources.length) params.set("source", view.sources.join(","));
  if (view.since) params.set("since", view.since);
  if (view.q) params.set("q", view.q);
  if (view.sort && view.sort !== "score") params.set("sort", view.sort);
  if (view.page && view.page > 1) params.set("page", String(view.page));
  const query = params.toString();
  return query ? `/my-jobs?${query}` : "/my-jobs";
}

export function parseRoute(hash) {
  const raw = (hash || "").replace(/^#/, "") || "/";
  const cut = raw.indexOf("?");
  const path = cut === -1 ? raw : raw.slice(0, cut);
  const query = cut === -1 ? "" : raw.slice(cut + 1);
  const search = path.match(/^\/search\/(\d+)$/);
  if (search) return { name: "search", id: Number(search[1]) };
  if (path === "/my-jobs") return myJobsRoute(query);
  if (path === "/settings") return { name: "settings" };
  return { name: "home" };
}

export function currentRoute() {
  return parseRoute(location.hash);
}

export function onRoute(fn) {
  window.addEventListener("hashchange", () => fn(currentRoute()));
}

export function go(path) {
  location.hash = "#" + path;
}
