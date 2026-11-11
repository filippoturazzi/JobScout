// The sidebar: logo, new search, the searches list, My jobs, Settings.
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { go } from "./router.js";
import { refreshSearches } from "./store.js";

// The search whose delete was refused (a run is going, or the request failed).
let errorFor = null; // { id, key }

// "Delete this search?" asks in a modal dialog centred on the page. It lives on <body>, not in
// the sidebar, so re-rendering the sidebar never tears it down while it is open.
let dialog = null;

function confirmDelete(s, route, rerender) {
  errorFor = null;
  if (dialog) dialog.remove();
  const close = () => dialog.close();
  const confirm = h(
    "button",
    { class: "js-btn js-btn--secondary cd-delete", type: "button", onclick: () => remove(s.id, route, rerender, confirm) },
    icon("trash"),
    t("delete"),
  );
  dialog = h(
    "dialog",
    {
      class: "cd",
      "aria-labelledby": "cd-title",
      "aria-describedby": "cd-body",
      // A click on the backdrop lands on the dialog itself: treat it as Cancel.
      onclick: (e) => { if (e.target === dialog) close(); },
      onclose: () => { dialog.remove(); dialog = null; },
    },
    h("h2", { class: "text-h2 cd-title", id: "cd-title" }, t("delete_confirm")),
    h(
      "p",
      { class: "text-body cd-body", id: "cd-body" },
      t("delete_confirm_body", { title: s.title }),
    ),
    h(
      "div",
      { class: "cd-actions" },
      h("button", { class: "js-btn js-btn--ghost", type: "button", autofocus: true, onclick: close }, t("cancel")),
      confirm,
    ),
  );
  document.body.appendChild(dialog);
  dialog.showModal();
}

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
        onclick: () => confirmDelete(s, route, rerender),
      },
      icon("trash"),
    ),
    errorFor && errorFor.id === s.id ? h("p", { class: "text-body-sm sb-error", role: "alert" }, t(errorFor.key)) : null,
  );
}

async function remove(id, route, rerender, button) {
  button.disabled = true;
  try {
    await api.del(`/searches/${id}`);
    if (dialog) dialog.close();
    errorFor = null;
    if (route.name === "search" && route.id === id) go("/");
    await refreshSearches();
  } catch (e) {
    if (dialog) dialog.close();
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
