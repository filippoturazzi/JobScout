// My jobs (#/my-jobs): every job the user's searches found, once each, across all searches.
// The whole view lives in the hash (router.js), so the page can be reloaded or shared as it is.
// Tabs and the search picker navigate; the text search, the sort, the filters and the page
// rewrite the hash in place and redraw the list, so the filters popover stays open while it
// applies them live. A late response never paints over another route: the shell calls
// leaveMyJobs() when it moves on.
import { h, mount } from "../dom.js";
import { icon } from "../icons.js";
import { t } from "../i18n.js";
import { api } from "../api.js";
import { go, MIN_SCORES, MY_JOBS_TABS, myJobsPath, SINCES, SORTS, WORK_MODES } from "../router.js";
import { createGuard } from "../guard.js";
import { jobRow, jobRowHeader } from "../jobcard.js";
import { nextStatus, openDetail, sendVerdict } from "../detail.js";
import { apiQuery, clearFilters, filterChips, filterCount, pageInfo } from "../myjobsview.js";
import { closePopover, isOpenFor, togglePopover, toggleMenu } from "../popover.js";
import { showToast } from "../toast.js";
import { sourceName } from "../format.js";

const guard = createGuard();
let detail = null;
let detailRoot = null;
let focusTab = false; // a tab was just chosen: keep the keyboard on the tab bar after the redraw

const SEARCH_DELAY_MS = 250;

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
  closePopover({ restoreFocus: false });
}

function chipLabel(chip) {
  if (chip.kind === "min") return t("chip_min", { n: chip.value });
  if (chip.kind === "mode") return t(`mode_${chip.value}`);
  if (chip.kind === "source") return sourceName(chip.value);
  return t(`since_${chip.value}`);
}

function segmented(label, options, current, onPick, key) {
  return h(
    "div",
    { class: "set-seg mj-seg", role: "radiogroup", "aria-label": label },
    options.map((o) =>
      h(
        "button",
        {
          class: "set-seg__opt text-body-sm",
          type: "button",
          role: "radio",
          "aria-checked": o.value === current ? "true" : "false",
          "data-key": `${key}:${o.value}`,
          onclick: () => onPick(o.value),
        },
        o.label,
      ),
    ),
  );
}

function chipToggles(label, options, chosen, onToggle, key) {
  return h(
    "div",
    { class: "mj-chips", role: "group", "aria-label": label },
    options.map((o) => {
      const on = chosen.includes(o.value);
      return h(
        "button",
        { class: "mj-chip text-body-sm", type: "button", "aria-pressed": on ? "true" : "false", "data-key": `${key}:${o.value}`, onclick: () => onToggle(o.value) },
        on ? icon("check", 14) : null,
        o.label,
      );
    }),
  );
}

// Keeps `button` in a .mj-pop wrapper (position: relative) that its popover opens into.
function wrapped(button) {
  const parent = button.parentElement;
  return parent && parent.classList.contains("mj-pop") ? parent : h("span", { class: "mj-pop" }, button);
}

export async function renderMyJobs(root, ctx, route) {
  const mine = guard.next();
  closeDetail();
  closePopover({ restoreFocus: false });
  let view = route;
  const title = h("h1", { class: "text-h1 app-title" }, t("my_jobs"));
  // A redraw of this same page keeps what it shows until the new list is in: no flash.
  if (!root.querySelector(".mj")) mount(root, h("div", { class: "app-column app-column--wide mj" }, title));

  let data;
  try {
    data = await api.get(`/my-jobs?${apiQuery(view)}`);
  } catch (e) {
    if (!guard.isCurrent(mine)) return;
    mount(root, h("div", { class: "app-column app-column--wide mj" }, title, h("p", { class: "text-body conv-error", role: "alert" }, t("request_failed"))));
    return;
  }
  if (!guard.isCurrent(mine)) return;

  const status = ctx.state.status || {};
  const activeSources = (status.sources || []).filter((s) => s.active).map((s) => s.name);
  // A filter on a source that is off now still shows, so it can be taken off.
  const sourceOptions = [...new Set([...activeSources, ...view.sources])];

  let selectedId = null;
  const detailHost = h("aside", { class: "app-detail", hidden: true, "aria-label": t("job_detail") });
  const sub = h("p", { class: "text-body-sm mj-sub" });
  const actionsHost = h("div", { class: "mj-actions" });
  const tabsHost = h("div", { class: "mj-tabs", role: "tablist", "aria-label": t("my_jobs_tabs") });
  const chipsHost = h("div", { class: "mj-applied" });
  const listHost = h("div", { class: "mj-panel", id: "mj-panel", role: "tabpanel", "aria-labelledby": `mj-tab-${view.tab}` });
  const filterPanel = h("div", { class: "mj-filters", role: "dialog", "aria-label": t("filters") });

  // --- Changing the view ------------------------------------------------------------------

  // Navigations (a tab, the search picker): a new history entry and a fresh render.
  const navigate = (next) => go(myJobsPath({ ...next, page: 1 }));

  // In place: the hash is rewritten without a history entry, and only the list is read again.
  let loading = 0;
  async function setView(next) {
    view = next;
    history.replaceState(null, "", "#" + myJobsPath(view));
    const ticket = ++loading;
    try {
      const fresh = await api.get(`/my-jobs?${apiQuery(view)}`);
      if (!guard.isCurrent(mine) || ticket !== loading) return;
      data = fresh;
    } catch (e) {
      if (!guard.isCurrent(mine) || ticket !== loading) return;
      showToast({ message: t("request_failed"), kind: "error" });
    }
    draw();
  }

  const withFilters = (change) => setView({ ...view, ...change, page: 1 });

  // --- Header: search picker, text search, sort, filters ------------------------------------

  let findOpen = Boolean(view.q);
  let findTimer = null;
  const findInput = h("input", {
    class: "mj-find__input text-body-sm",
    type: "search",
    value: view.q,
    placeholder: t("find_placeholder"),
    "aria-label": t("find_jobs"),
    oninput: (event) => {
      clearTimeout(findTimer);
      const q = event.target.value.trim();
      findTimer = setTimeout(() => withFilters({ q }), SEARCH_DELAY_MS);
    },
    onkeydown: (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      findInput.value = "";
      findOpen = false;
      clearTimeout(findTimer);
      if (view.q) withFilters({ q: "" });
      else drawActions();
      findButton.focus();
    },
  });
  const findWrap = h("span", { class: "mj-find" }, icon("search", 16), findInput);
  const findButton = h(
    "button",
    {
      class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--outline",
      type: "button",
      "aria-label": t("find_jobs"),
      title: t("find_jobs"),
      onclick: () => {
        findOpen = true;
        drawActions();
        findInput.focus();
      },
    },
    icon("search", 16),
  );

  const sortButton = h(
    "button",
    {
      class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--outline",
      type: "button",
      "aria-haspopup": "menu",
      "aria-expanded": "false",
      onclick: () =>
        toggleMenu(
          sortButton,
          t("sort"),
          SORTS.map((value) => ({ label: t(`sort_${value}`), checked: view.sort === value, run: () => withFilters({ sort: value }) })),
        ),
    },
    icon("arrow-down-wide-narrow", 16),
  );

  const filterButton = h(
    "button",
    {
      class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--outline mj-filter-btn",
      type: "button",
      "aria-haspopup": "dialog",
      "aria-expanded": "false",
      onclick: () => {
        if (togglePopover(filterButton, filterPanel)) {
          drawFilters();
          const first = filterPanel.querySelector('[aria-checked="true"], .mj-filters__body button');
          if (first) first.focus();
        }
      },
    },
    icon("sliders-horizontal", 16),
  );

  const picker = h(
    "span",
    { class: "mj-filter" },
    h(
      "select",
      {
        class: "js-btn js-btn--secondary mj-select text-body-sm",
        "aria-label": t("filter_by_search"),
        onchange: (event) => {
          const value = Number(event.target.value);
          navigate({ ...view, search: value > 0 ? value : null });
        },
      },
      h("option", { value: "" }, t("all_searches")),
      ctx.state.searches.map((s) => h("option", { value: s.id, selected: s.id === view.search }, s.title)),
    ),
    icon("chevron-down", 16),
  );

  function drawActions() {
    const n = filterCount(view);
    const sortLabel = `${t("sort")}: ${t(`sort_${view.sort}`)}`;
    sortButton.setAttribute("aria-label", sortLabel);
    sortButton.setAttribute("title", sortLabel);
    sortButton.setAttribute("aria-pressed", view.sort !== "score" ? "true" : "false");
    const filterLabel = n ? t("filters_on", { n }) : t("filters");
    filterButton.setAttribute("aria-label", filterLabel);
    filterButton.setAttribute("title", filterLabel);
    filterButton.setAttribute("aria-pressed", n ? "true" : "false");
    // Moving a focused element drops its focus: the redraw gives it back (the sort button after
    // its menu, the text field while typing).
    const focused = actionsHost.contains(document.activeElement) ? document.activeElement : null;
    // An open popover lives in its button's wrapper: redraws keep it there.
    const filterWrap = wrapped(filterButton);
    mount(filterWrap, filterButton, n ? h("span", { class: "text-meta mj-badge", "aria-hidden": "true" }, n) : null, isOpenFor(filterButton) ? filterPanel : null);
    mount(actionsHost, picker, findOpen ? findWrap : findButton, wrapped(sortButton), filterWrap);
    if (focused && focused.isConnected && document.activeElement !== focused) focused.focus();
  }

  // --- The filters popover ----------------------------------------------------------------

  function drawFilters() {
    const focused = filterPanel.contains(document.activeElement) ? document.activeElement.getAttribute("data-key") : null;
    const toggleIn = (list, value) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
    const field = (label, control) => h("div", { class: "mj-field" }, h("p", { class: "text-meta mj-field__label" }, label), control);
    mount(
      filterPanel,
      h(
        "div",
        { class: "mj-filters__head" },
        h("h2", { class: "text-label" }, t("filters")),
        h("button", { class: "js-btn js-btn--ghost mj-clear text-body-sm", type: "button", "data-key": "clear", disabled: !filterCount(view), onclick: () => withFilters(clearFilters(view)) }, t("clear")),
      ),
      h(
        "div",
        { class: "mj-filters__body" },
        field(t("min_fit"), segmented(t("min_fit"), MIN_SCORES.map((n) => ({ value: n, label: n ? `≥ ${n}%` : t("any") })), view.min, (min) => withFilters({ min }), "min")),
        field(t("work_mode"), chipToggles(t("work_mode"), WORK_MODES.map((m) => ({ value: m, label: t(`mode_${m}`) })), view.modes, (m) => withFilters({ modes: toggleIn(view.modes, m) }), "mode")),
        sourceOptions.length
          ? field(t("source"), chipToggles(t("source"), sourceOptions.map((s) => ({ value: s, label: sourceName(s) })), view.sources, (s) => withFilters({ sources: toggleIn(view.sources, s) }), "source"))
          : null,
        field(
          t("posted"),
          segmented(t("posted"), [...SINCES.map((s) => ({ value: s, label: t(`since_${s}`) })), { value: null, label: t("since_any") }], view.since, (since) => withFilters({ since }), "since"),
        ),
      ),
      h(
        "div",
        { class: "mj-filters__foot" },
        h("button", { class: "js-btn js-btn--primary mj-see", type: "button", "data-key": "see", onclick: () => closePopover() }, t("see_n_jobs", { n: data.total })),
      ),
    );
    if (focused) {
      const again = filterPanel.querySelector(`[data-key="${focused}"]`);
      if (again && !again.disabled) again.focus();
    }
  }

  // --- Tabs, applied filters, list, pages -------------------------------------------------

  function drawTabs() {
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
            "aria-selected": name === view.tab ? "true" : "false",
            "aria-controls": "mj-panel",
            tabindex: name === view.tab ? "0" : "-1",
            onclick: () => {
              if (name === view.tab) return;
              focusTab = true;
              navigate({ ...view, tab: name });
            },
            onkeydown: (event) => {
              const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              if (!step) return;
              event.preventDefault();
              focusTab = true;
              navigate({ ...view, tab: MY_JOBS_TABS[(index + step + MY_JOBS_TABS.length) % MY_JOBS_TABS.length] });
            },
          },
          t(`tab_${name}`),
          h("span", { class: "text-meta mj-count" }, data.counts[name] ?? 0),
        ),
      ),
    );
  }

  function drawChips() {
    const chips = filterChips(view);
    chipsHost.hidden = !chips.length;
    mount(
      chipsHost,
      chips.map((chip) =>
        h(
          "button",
          { class: "mj-applied__chip text-body-sm", type: "button", "aria-label": t("remove_filter", { name: chipLabel(chip) }), onclick: () => setView(chip.without) },
          chipLabel(chip),
          icon("x", 12),
        ),
      ),
      chips.length ? h("button", { class: "js-btn js-btn--ghost mj-clear text-body-sm", type: "button", onclick: () => withFilters(clearFilters(view)) }, t("clear_all")) : null,
    );
  }

  async function saveFromRow(match) {
    try {
      await sendVerdict(match, nextStatus(match.status, "saved"), onVerdict);
    } catch (e) {
      showToast({ message: t("request_failed"), kind: "error" });
    }
  }

  function drawList() {
    // A page past the end (its last job just left, or an old link) goes back to the first.
    if (!data.items.length && view.page > 1) {
      setView({ ...view, page: 1 });
      return;
    }
    if (!data.items.length) {
      const filtered = filterCount(view) > 0 || Boolean(view.q);
      const clearEverything = () => {
        findInput.value = "";
        findOpen = false;
        withFilters({ ...clearFilters(view), q: "" });
      };
      mount(
        listHost,
        filtered
          ? h(
              "div",
              { class: "mj-empty" },
              h("span", { class: "mj-empty__icon" }, icon("search", 20)),
              h("p", { class: "text-body" }, t("mj_empty_filtered")),
              h("p", { class: "text-body-sm mj-empty__hint" }, filterCount(view) ? t("mj_empty_filtered_hint") : t("mj_empty_find_hint", { q: view.q })),
              h("button", { class: "js-btn js-btn--secondary", type: "button", onclick: clearEverything }, icon("rotate-ccw", 16), t("clear_filters")),
            )
          : h("div", { class: "mj-empty" }, h("p", { class: "text-body" }, t(`mj_empty_${view.tab}`)), h("p", { class: "text-body-sm mj-empty__hint" }, t(`mj_empty_${view.tab}_hint`))),
      );
      return;
    }
    const pages = pageInfo(view.page, data.total);
    const turn = (page, key) => {
      setView({ ...view, page }).then(() => {
        const again = listHost.querySelector(`[data-pager="${key}"]`);
        if (again && !again.disabled) again.focus();
      });
      const scroller = root.closest(".app-content");
      if (scroller) scroller.scrollTo({ top: 0 });
    };
    const pager = (key, enabled, label, iconName, page) =>
      h(
        "button",
        { class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--sm js-icon-btn--outline", type: "button", "data-pager": key, disabled: !enabled, "aria-label": label, title: label, onclick: () => turn(page, key) },
        icon(iconName, 16),
      );
    mount(
      listHost,
      jobRowHeader(),
      h(
        "div",
        { class: "mj-rows", role: "listbox", "aria-label": t("my_jobs") },
        data.items.map((item) => jobRow(item.match, { selected: item.match.id === selectedId, onOpen: openMatch, searches: item.searches, onSave: saveFromRow })),
      ),
      h(
        "nav",
        { class: "mj-pager", "aria-label": t("pages") },
        h("p", { class: "text-body-sm mj-pager__text" }, t("showing_range", { from: pages.from, to: pages.to, n: data.total })),
        pages.pages > 1
          ? h("div", { class: "mj-pager__btns" }, pager("prev", pages.prev, t("page_prev"), "chevron-left", view.page - 1), pager("next", pages.next, t("page_next"), "chevron-right", view.page + 1))
          : null,
      ),
    );
  }

  function draw() {
    sub.textContent = t("my_jobs_sub", { n: data.counts.all ?? 0 });
    drawActions();
    drawTabs();
    drawChips();
    drawList();
    if (isOpenFor(filterButton)) drawFilters();
  }

  // After a verdict the counts and the list are read again; the panel is left alone.
  function onVerdict(updated) {
    // A verdict is about the job: All drops what is dismissed, another tab what left its status.
    const leaves = view.tab === "all" ? updated.status === "dismissed" : updated.status !== view.tab;
    data = {
      ...data,
      items: leaves ? data.items.filter((i) => i.match.id !== updated.id) : data.items.map((i) => (i.match.id === updated.id ? { ...i, match: updated } : i)),
    };
    drawList();
    setView(view);
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
  mount(
    root,
    h(
      "div",
      { class: "app-column app-column--wide mj" },
      h("div", { class: "mj-head" }, h("div", { class: "mj-head__text" }, title, sub), actionsHost),
      h("div", { class: "mj-bar" }, tabsHost),
      chipsHost,
      listHost,
    ),
    detailHost,
  );
  // The palette sent us to a saved job: open it, and drop open= so a redraw does not reopen it.
  if (view.open) {
    const wanted = view.open;
    view = { ...view, open: null };
    history.replaceState(null, "", "#" + myJobsPath(view));
    const item = data.items.find((i) => i.match.id === wanted);
    if (item) openMatch(item.match);
  }
  if (focusTab) {
    focusTab = false;
    const selected = tabsHost.querySelector('[aria-selected="true"]');
    if (selected) selected.focus();
  }
}
