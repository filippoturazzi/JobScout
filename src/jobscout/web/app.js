// The page's entry point: status, locale, theme, sidebar and the route's view.
import { h, mount } from "./js/dom.js";
import { icon } from "./js/icons.js";
import { loadLocale, t } from "./js/i18n.js";
import { applyTheme, watchSystemTheme } from "./js/theme.js";
import { currentRoute, go, onRoute } from "./js/router.js";
import { refreshSearches, refreshStatus, runningMismatch, shouldWatch, state, subscribe } from "./js/store.js";
import { renderSidebar } from "./js/sidebar.js";
import { initToasts } from "./js/toast.js";
import { listenForShortcuts } from "./js/shortcuts.js";
import { togglePalette } from "./js/palette.js";
import { renderHome } from "./js/views/home.js";
import { renderSettings } from "./js/views/settings.js";
import { isPollingRun, leaveSearch, renderSearch } from "./js/views/search.js";
import { leaveMyJobs, renderMyJobs } from "./js/views/myjobs.js";

const WATCH_MS = 2000;
const SIDEBAR_KEY = "jobscout.sidebar";

function readFolded() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === "collapsed";
  } catch (e) {
    return false;
  }
}

async function start() {
  applyTheme();
  watchSystemTheme();
  const root = document.getElementById("app");
  const sidebar = h("aside", { class: "app-sidebar", id: "sidebar" });
  const main = h("main", { class: "app-main" });
  const menuButton = h("button", { class: "js-btn js-btn--ghost app-menu", type: "button", "aria-controls": "sidebar", "aria-expanded": "false", "aria-label": t("menu") }, icon("menu", 20));
  const toasts = h("div", { class: "toast-host", role: "status", "aria-live": "polite" });
  const shell = h("div", { class: "app-shell" }, sidebar, h("div", { class: "app-content" }, menuButton, main), toasts);
  initToasts(toasts);
  function setMenuOpen(open) {
    shell.classList.toggle("is-menu-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
  }
  menuButton.addEventListener("click", () => setMenuOpen(!shell.classList.contains("is-menu-open")));
  mount(root, shell);

  // Folding is for wide screens; below 800 px the sidebar is a drawer and its fold button closes it.
  const narrow = matchMedia("(max-width: 800px)");
  let folded = readFolded();
  const isFolded = () => folded && !narrow.matches;
  const drawSidebar = () => {
    shell.classList.toggle("is-collapsed", isFolded());
    renderSidebar(sidebar, state, currentRoute(), { collapsed: isFolded(), actions: { toggle: toggleSidebar, search: palette } });
  };
  const palette = () => togglePalette(() => state.searches);
  function toggleSidebar() {
    if (narrow.matches) {
      setMenuOpen(!shell.classList.contains("is-menu-open"));
      if (!shell.classList.contains("is-menu-open")) menuButton.focus();
      return;
    }
    folded = !folded;
    try {
      localStorage.setItem(SIDEBAR_KEY, folded ? "collapsed" : "open");
    } catch (e) {
      // Storage can be blocked; the sidebar still folds for this visit.
    }
    drawSidebar();
    const fold = sidebar.querySelector('[aria-controls="sidebar"]');
    if (fold) fold.focus();
  }
  narrow.addEventListener("change", () => drawSidebar());

  // A new search from anywhere: home, with the composer ready to type in.
  function newSearch() {
    if (currentRoute().name !== "home") go("/");
    setTimeout(() => {
      const box = main.querySelector("textarea");
      if (box) box.focus();
    }, 0);
  }
  listenForShortcuts({ palette, sidebar: toggleSidebar, new: newSearch });

  // While a search runs, the sidebar's running marker follows /status, whichever view is open:
  // a silent poll every 2 s, a silent re-read of the list when the two disagree, and a redraw
  // of the sidebar alone (a store notification would redraw My jobs and close its panel). The
  // open search's own polling already reads /status, so the watcher waits while it runs.
  let watchTimer = null;
  function watch() {
    if (watchTimer === null && shouldWatch(state.status, state.searches)) watchTimer = setTimeout(tick, WATCH_MS);
  }
  async function tick() {
    if (!isPollingRun()) {
      try {
        await refreshStatus({ silent: true });
        if (runningMismatch(state.status, state.searches)) {
          await refreshSearches({ silent: true });
          drawSidebar();
        }
      } catch (e) {
        // Keep what we knew; the next tick asks again.
      }
    }
    watchTimer = null;
    watch();
  }

  // The sidebar redraws on every change; the main view only when the route changes or a view asks
  // for it (a language switch), so typing in the composer is never wiped by a background refresh.
  let mountedKey = null;
  function render(force = false) {
    const route = currentRoute();
    if (route.name !== "search") leaveSearch();
    if (route.name !== "my-jobs") leaveMyJobs();
    drawSidebar();
    const key = route.name === "search" ? `search:${route.id}` : route.name;
    if (force === true || key !== mountedKey || key === "my-jobs") {
      mountedKey = key;
      const ctx = { state, rerender: () => render(true) };
      if (route.name === "home") renderHome(main, ctx);
      else if (route.name === "settings") renderSettings(main, ctx);
      else if (route.name === "search") renderSearch(main, ctx, route.id);
      else renderMyJobs(main, ctx, route);
    }
    setMenuOpen(false);
    watch();
  }

  // Each step on its own: a list that fails to load must not turn a pt-BR page English.
  let locale = "en";
  try {
    const status = await refreshStatus();
    locale = status.locale || "en";
  } catch (e) {
    console.error(e);
  }
  try {
    await loadLocale(locale);
  } catch (e) {
    console.error(e);
    locale = "en";
    await loadLocale(locale);
  }
  document.documentElement.lang = locale;
  try {
    await refreshSearches();
  } catch (e) {
    console.error(e);
  }
  subscribe(() => render());
  onRoute(() => render());
  render(true);
}

start();
