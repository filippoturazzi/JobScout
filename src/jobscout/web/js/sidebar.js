// The sidebar: logo, new search, the searches list, My jobs, Settings.
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { go } from "./router.js";
import { refreshSearches } from "./store.js";

// Which search row is asking "Delete this search?", and which one was refused because a run is going.
let confirmingId = null;
let errorFor = null; // { id, key }

function navLink(href, name, iconName, route, routeName) {
  const current = route.name === routeName;
  return h(
    "a",
    { class: "js-btn js-btn--ghost sb-link", href, "aria-current": current ? "page" : null },
    icon(iconName),
    t(name),
  );
}

function searchRow(s, route, rerender) {
  const current = route.name === "search" && route.id === s.id;
  if (confirmingId === s.id) {
    return h(
      "li",
      { class: "sb-row sb-row--confirm" },
      h("span", { class: "text-body-sm" }, t("delete_confirm")),
      h(
        "span",
        { class: "sb-confirm" },
        h("button", { class: "js-btn js-btn--ghost", type: "button", onclick: () => remove(s.id, route, rerender) }, t("delete")),
        h("button", { class: "js-btn js-btn--ghost", type: "button", onclick: () => { confirmingId = null; rerender(); } }, t("cancel")),
      ),
    );
  }
  return h(
    "li",
    { class: "sb-row" },
    h(
      "a",
      { class: "sb-item text-body", href: `#/search/${s.id}`, "aria-current": current ? "page" : null },
      h("span", { class: "sb-item__title" }, s.title),
      s.running ? [icon("loader"), h("span", { class: "sr-only" }, t("search_running"))] : null,
    ),
    h(
      "button",
      {
        class: "js-btn js-btn--ghost sb-del",
        type: "button",
        "aria-label": `${t("delete")}: ${s.title}`,
        onclick: () => { confirmingId = s.id; errorFor = null; rerender(); },
      },
      icon("trash"),
    ),
    errorFor && errorFor.id === s.id ? h("p", { class: "text-body-sm sb-error", role: "alert" }, t(errorFor.key)) : null,
  );
}

async function remove(id, route, rerender) {
  try {
    await api.del(`/searches/${id}`);
    confirmingId = null;
    errorFor = null;
    if (route.name === "search" && route.id === id) go("/");
    await refreshSearches();
  } catch (e) {
    confirmingId = null;
    errorFor = { id, key: e && e.code === "search_busy" ? "search_busy" : "delete_failed" };
    rerender();
  }
}

export function renderSidebar(root, state, route, rerender) {
  const searches = [...state.searches].sort((a, b) => String(b.last_used_at).localeCompare(String(a.last_used_at)));
  mount(
    root,
    h(
      "a",
      { class: "js-logo sb-logo", href: "#/", "aria-label": "jobscout" },
      h("img", { src: "/static/design/logos/jobscout-mark.svg", alt: "" }),
      "jobscout",
    ),
    h("a", { class: "js-btn js-btn--secondary sb-new", href: "#/" }, icon("plus"), t("new_search")),
    h(
      "nav",
      { class: "sb-searches", "aria-label": t("searches") },
      h("h2", { class: "text-meta sb-heading" }, t("searches")),
      searches.length
        ? h("ul", { class: "sb-list" }, searches.map((s) => searchRow(s, route, rerender)))
        : h("p", { class: "text-body-sm sb-empty" }, t("searches_empty")),
    ),
    h(
      "div",
      { class: "sb-foot" },
      navLink("#/my-jobs", "my_jobs", "bookmark", route, "my-jobs"),
      navLink("#/settings", "settings", "settings", route, "settings"),
    ),
  );
}
