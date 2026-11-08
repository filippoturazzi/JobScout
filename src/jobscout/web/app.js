// The page's entry point: status, locale, theme, sidebar and the route's view (my jobs is a stub until a later task).
import { h, mount } from "./js/dom.js";
import { icon } from "./js/icons.js";
import { loadLocale, t } from "./js/i18n.js";
import { currentRoute, onRoute } from "./js/router.js";
import { refreshSearches, refreshStatus, state, subscribe } from "./js/store.js";
import { renderSidebar } from "./js/sidebar.js";
import { renderHome } from "./js/views/home.js";
import { renderSettings } from "./js/views/settings.js";
import { renderSearch } from "./js/views/search.js";

function applyTheme() {
  let theme = "dark";
  try {
    const saved = localStorage.getItem("jobscout.theme");
    if (saved === "light" || saved === "dark") theme = saved;
  } catch (e) {
    // Storage can be blocked; dark is the default.
  }
  document.documentElement.dataset.theme = theme;
}

function viewTitle(route) {
  if (route.name === "my-jobs") return t("my_jobs");
  if (route.name === "settings") return t("settings");
  if (route.name === "search") {
    const found = state.searches.find((s) => s.id === route.id);
    return found ? found.title : t("search_title", { id: route.id });
  }
  return t("home_title");
}

async function start() {
  applyTheme();
  const root = document.getElementById("app");
  const sidebar = h("aside", { class: "app-sidebar", id: "sidebar" });
  const main = h("main", { class: "app-main" });
  const menuButton = h("button", { class: "js-btn js-btn--ghost app-menu", type: "button", "aria-controls": "sidebar", "aria-expanded": "false", "aria-label": t("menu") }, icon("menu", 20));
  const shell = h("div", { class: "app-shell" }, sidebar, h("div", { class: "app-content" }, menuButton, main));
  menuButton.addEventListener("click", () => {
    const open = !shell.classList.contains("is-menu-open");
    shell.classList.toggle("is-menu-open", open);
    menuButton.setAttribute("aria-expanded", String(open));
  });
  mount(root, shell);

  // The sidebar redraws on every change; the main view only when the route changes or a view asks
  // for it (a language switch), so typing in the composer is never wiped by a background refresh.
  let mountedKey = null;
  function render(force = false) {
    const route = currentRoute();
    renderSidebar(sidebar, state, route, () => render());
    const key = route.name === "search" ? `search:${route.id}` : route.name;
    if (force === true || key !== mountedKey || key === "my-jobs") {
      mountedKey = key;
      const ctx = { state, rerender: () => render(true) };
      if (route.name === "home") renderHome(main, ctx);
      else if (route.name === "settings") renderSettings(main, ctx);
      else if (route.name === "search") renderSearch(main, ctx, route.id);
      else mount(main, h("div", { class: "app-column" }, h("h1", { class: "text-h1 app-title" }, viewTitle(route))));
    }
    shell.classList.remove("is-menu-open");
    menuButton.setAttribute("aria-expanded", "false");
  }

  try {
    const status = await refreshStatus();
    await loadLocale(status.locale || "en");
    document.documentElement.lang = status.locale || "en";
    await refreshSearches();
  } catch (e) {
    console.error(e);
    await loadLocale("en");
  }
  subscribe(() => render());
  onRoute(() => render());
  render(true);
}

start();
