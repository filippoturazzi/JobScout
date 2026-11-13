// The sidebar: logo, new search, the searches list grouped by day, My jobs, Settings, and the
// "running locally" footer with the repository link.
import { h, mount } from "./dom.js";
import { icon, logoMark } from "./icons.js";
import { dayGroup } from "./format.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { go } from "./router.js";
import { hideSearch, refreshSearches, unhideSearch } from "./store.js";
import { showToast } from "./toast.js";

export const REPO_URL = "https://github.com/filippoturazzi/JobScout";

// "Delete this search?" asks in a modal dialog centred on the page. It lives on <body>, not in
// the sidebar, so re-rendering the sidebar never tears it down while it is open.
let dialog = null;

function confirmDelete(s, route) {
  if (dialog) dialog.remove();
  const close = () => dialog.close();
  const confirm = h(
    "button",
    { class: "js-btn js-btn--danger cd-delete", type: "button", onclick: () => remove(s, route) },
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
    h("span", { class: "cd-icon" }, icon("trash", 18)),
    h("h2", { class: "text-h2 cd-title", id: "cd-title" }, t("delete_confirm")),
    h(
      "p",
      { class: "text-body-sm cd-body", id: "cd-body" },
      t("delete_confirm_body", { title: s.title }),
    ),
    h(
      "div",
      { class: "cd-actions" },
      // Cancel takes the focus first, so Enter never deletes by accident.
      h("button", { class: "js-btn js-btn--secondary", type: "button", autofocus: true, onclick: close }, t("cancel")),
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
    { class: "sb-link text-body-sm", href, "aria-current": current ? "page" : null },
    icon(iconName),
    t(name),
  );
}

function searchRow(s, route) {
  const current = route.name === "search" && route.id === s.id;
  return h(
    "li",
    { class: "sb-row" },
    h(
      "a",
      { class: "sb-item text-body-sm", href: `#/search/${s.id}`, "aria-current": current ? "page" : null },
      h("span", { class: "sb-item__title" }, s.title),
      s.running ? [icon("loader"), h("span", { class: "sr-only" }, t("search_running"))] : null,
    ),
    h(
      "button",
      {
        class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--sm sb-del",
        type: "button",
        "aria-label": `${t("delete")}: ${s.title}`,
        title: t("delete"),
        onclick: () => confirmDelete(s, route),
      },
      icon("trash", 14),
    ),
  );
}

// Deletes that wait for their toast to go: the search is hidden at once, the DELETE is sent
// when the toast expires (or the page is left), and Undo brings the search back.
const pending = new Set();

async function sendDelete(id) {
  if (!pending.delete(id)) return;
  try {
    await api.del(`/searches/${id}`);
    unhideSearch(id);
  } catch (e) {
    unhideSearch(id);
    showToast({ message: t(e && e.code === "search_busy" ? "search_busy" : "delete_failed"), kind: "error" });
    await refreshSearches().catch(() => {});
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => {
    for (const id of pending) fetch(`/searches/${id}`, { method: "DELETE", keepalive: true });
    pending.clear();
  });
}

function remove(s, route) {
  if (dialog) dialog.close();
  if (s.running) {
    showToast({ message: t("search_busy"), kind: "error" });
    return;
  }
  pending.add(s.id);
  if (route.name === "search" && route.id === s.id) go("/");
  hideSearch(s.id);
  showToast({
    message: t("search_deleted"),
    onExpire: () => sendDelete(s.id),
    action: {
      label: t("undo"),
      run: () => {
        pending.delete(s.id);
        unhideSearch(s.id);
        refreshSearches().catch(() => {});
      },
    },
  });
}

const GROUPS = ["today", "week", "older"];

// The searches, most recent first, split into Today / This week / Older (empty groups dropped).
export function groupSearches(searches, now = new Date()) {
  const sorted = [...searches].sort((a, b) => String(b.last_used_at).localeCompare(String(a.last_used_at)));
  return GROUPS.map((name) => ({ name, items: sorted.filter((s) => dayGroup(s.last_used_at, now) === name) })).filter((g) => g.items.length);
}

export function renderSidebar(root, state, route) {
  const groups = groupSearches(state.searches);
  mount(
    root,
    h(
      "a",
      { class: "js-logo sb-logo", href: "#/", "aria-label": "jobscout" },
      logoMark(26),
      h("span", { "aria-hidden": "true" }, "jobscout"),
    ),
    // New search always carries the highlight; on the home screen it is also where you are.
    h(
      "a",
      { class: "js-btn js-btn--secondary sb-new js-highlight text-body-sm", href: "#/", "aria-current": route.name === "home" ? "page" : null },
      icon("square-pen"),
      t("new_search"),
    ),
    h(
      "nav",
      { class: "sb-searches", "aria-label": t("searches") },
      groups.length
        ? groups.map((g) =>
            h(
              "section",
              { class: "sb-group" },
              h("h2", { class: "text-meta sb-heading" }, t(`group_${g.name}`)),
              h("ul", { class: "sb-list" }, g.items.map((s) => searchRow(s, route))),
            ),
          )
        : [h("h2", { class: "text-meta sb-heading" }, t("searches")), h("p", { class: "text-body-sm sb-empty" }, t("searches_empty"))],
    ),
    h(
      "div",
      { class: "sb-foot" },
      navLink("#/my-jobs", "my_jobs", "bookmark", route, "my-jobs"),
      navLink("#/settings", "settings", "settings", route, "settings"),
      h(
        "div",
        { class: "sb-local" },
        h("span", { class: "text-meta sb-local__status" }, h("span", { class: "sb-local__dot", "aria-hidden": "true" }), t("running_locally")),
        h(
          "a",
          { class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--sm", href: REPO_URL, target: "_blank", rel: "noopener noreferrer", "aria-label": t("github_repo"), title: t("github_repo") },
          icon("github", 16),
        ),
      ),
    ),
  );
}
