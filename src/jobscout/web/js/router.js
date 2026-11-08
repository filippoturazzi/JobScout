// Hash routes: #/ (home), #/search/<id>, #/my-jobs, #/settings. Unknown routes are home.

export function parseRoute(hash) {
  const path = (hash || "").replace(/^#/, "") || "/";
  const search = path.match(/^\/search\/(\d+)$/);
  if (search) return { name: "search", id: Number(search[1]) };
  if (path === "/my-jobs") return { name: "my-jobs" };
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
