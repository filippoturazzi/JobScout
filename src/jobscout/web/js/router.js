// Hash routes: #/ (home), #/search/<id>, #/my-jobs[?tab=saved|applied&search=<id>], #/settings.
// Unknown routes are home.

export const MY_JOBS_TABS = ["all", "saved", "applied"];

function myJobsRoute(query) {
  const params = new URLSearchParams(query);
  const tab = params.get("tab");
  const raw = params.get("search");
  const id = raw !== null && /^\d+$/.test(raw) ? Number(raw) : 0;
  return { name: "my-jobs", tab: MY_JOBS_TABS.includes(tab) ? tab : "all", search: id > 0 ? id : null };
}

// The path (without "#") for My jobs, writing only what differs from the defaults.
export function myJobsPath(tab, search) {
  const params = new URLSearchParams();
  if (tab && tab !== "all") params.set("tab", tab);
  if (search) params.set("search", String(search));
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
