// My jobs (#/my-jobs): every job the user's searches found, once each, across all searches.
// Tabs All / Saved / Applied and the search filter live in the hash, so the page can be reloaded
// or shared as it is. A late response never paints over another route: the shell calls
// leaveMyJobs() when it moves on.
import { h, mount } from "../dom.js";
import { icon } from "../icons.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { go, MY_JOBS_TABS, myJobsPath } from "../router.js";
import { createGuard } from "../guard.js";
import { jobCard } from "../jobcard.js";
import { openDetail } from "../detail.js";

const guard = createGuard();
let detail = null;
let detailRoot = null;
let focusTab = false; // a tab was just chosen: keep the keyboard on the tab bar after the redraw

function closeDetail() {
  const open = detail;
  detail = null;
  if (open) open.close(false);
  if (detailRoot) detailRoot.classList.remove("has-detail");
  detailRoot = null;
}

export function leaveMyJobs() {
  guard.invalidate();
  closeDetail();
}

export async function renderMyJobs(root, ctx, route) {
  const mine = guard.next();
  closeDetail();
  const { tab, search } = route;
  const query = new URLSearchParams({ tab });
  if (search) query.set("search_id", String(search));
  const title = h("h1", { class: "text-h1 app-title" }, t("my_jobs"));
  mount(root, h("div", { class: "app-column app-column--wide" }, title));

  let data;
  try {
    data = await api.get(`/my-jobs?${query}`);
  } catch (e) {
    if (!guard.isCurrent(mine)) return;
    mount(root, h("div", { class: "app-column app-column--wide" }, title, h("p", { class: "text-body conv-error", role: "alert" }, t("request_failed"))));
    return;
  }
  if (!guard.isCurrent(mine)) return;

  let selectedId = null;
  const detailHost = h("aside", { class: "app-detail", hidden: true, "aria-label": t("job_detail") });
  const tabsHost = h("div", { class: "mj-tabs", role: "tablist", "aria-label": t("my_jobs_tabs") });
  const listHost = h("div", { class: "mj-panel", id: "mj-panel", role: "tabpanel", "aria-labelledby": `mj-tab-${tab}` });

  const choose = (nextTab) => {
    focusTab = true;
    go(myJobsPath(nextTab, search));
  };

  const filter = h(
    "span",
    { class: "mj-filter" },
    h(
      "select",
      {
        class: "js-btn js-btn--secondary mj-select",
        "aria-label": t("filter_by_search"),
        onchange: (event) => {
          const value = Number(event.target.value);
          go(myJobsPath(tab, value > 0 ? value : null));
        },
      },
      h("option", { value: "" }, t("all_searches")),
      ctx.state.searches.map((s) => h("option", { value: s.id, selected: s.id === search }, s.title)),
    ),
    icon("chevron-down", 16),
  );

  function drawTabs() {
    const labels = { all: t("tab_all"), saved: t("tab_saved"), applied: t("tab_applied") };
    mount(
      tabsHost,
      MY_JOBS_TABS.map((name, index) =>
        h(
          "button",
          {
            class: "mj-tab text-body",
            type: "button",
            role: "tab",
            id: `mj-tab-${name}`,
            "aria-selected": name === tab ? "true" : "false",
            "aria-controls": "mj-panel",
            tabindex: name === tab ? "0" : "-1",
            onclick: () => {
              if (name !== tab) choose(name);
            },
            onkeydown: (event) => {
              const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              if (!step) return;
              event.preventDefault();
              choose(MY_JOBS_TABS[(index + step + MY_JOBS_TABS.length) % MY_JOBS_TABS.length]);
            },
          },
          labels[name],
          h("span", { class: "text-meta mj-count" }, data.counts[name]),
        ),
      ),
    );
  }

  function drawList() {
    if (!data.items.length) {
      mount(
        listHost,
        h("div", { class: "mj-empty" }, h("p", { class: "text-body" }, t(`mj_empty_${tab}`)), h("p", { class: "text-body-sm mj-empty__hint" }, t(`mj_empty_${tab}_hint`))),
      );
      return;
    }
    mount(
      listHost,
      h(
        "div",
        { class: "run-cards", role: "listbox", "aria-label": t("my_jobs") },
        data.items.map((item) => jobCard(item.match, { selected: item.match.id === selectedId, onOpen: openMatch, searches: item.searches })),
      ),
    );
  }

  function draw() {
    drawTabs();
    drawList();
  }

  // After a verdict the counts and the list are read again; the panel is left alone.
  async function reload() {
    try {
      const fresh = await api.get(`/my-jobs?${query}`);
      if (!guard.isCurrent(mine)) return;
      data = fresh;
      draw();
    } catch (e) {
      // Keep the local update; the next visit asks again.
    }
  }

  function onVerdict(updated) {
    // A verdict is about the job: dismissed leaves every tab, another status leaves the other tabs.
    const leaves = updated.status === "dismissed" || (tab !== "all" && updated.status !== tab);
    data = {
      ...data,
      items: leaves ? data.items.filter((i) => i.match.id !== updated.id) : data.items.map((i) => (i.match.id === updated.id ? { ...i, match: updated } : i)),
    };
    draw();
    reload();
    if (!leaves) return null;
    return t(updated.status === "dismissed" ? "mj_dismissed" : "mj_left_tab");
  }

  function openMatch(match) {
    selectedId = match.id;
    if (detail) detail.update(match);
    else {
      detail = openDetail(detailHost, match, {
        onVerdict,
        onClose: () => {
          const closedId = selectedId;
          detail = null;
          selectedId = null;
          root.classList.remove("has-detail");
          detailRoot = null;
          if (!guard.isCurrent(mine)) return;
          drawList();
          const card = root.querySelector(`[data-match-id="${closedId}"]`);
          if (card) card.focus();
        },
      });
      root.classList.add("has-detail");
      detailRoot = root;
    }
    drawList();
  }

  draw();
  mount(root, h("div", { class: "app-column app-column--wide" }, title, h("div", { class: "mj-bar" }, tabsHost, filter), listHost), detailHost);
  if (focusTab) {
    focusTab = false;
    const selected = tabsHost.querySelector('[aria-selected="true"]');
    if (selected) selected.focus();
  }
}
