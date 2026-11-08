// The page's entry point: status, locale, theme, sidebar and the route's view (stubs until later tasks).
import { h, mount } from "./js/dom.js";
import { icon } from "./js/icons.js";
import { loadLocale, t } from "./js/i18n.js";
import { currentRoute, onRoute } from "./js/router.js";
import { refreshSearches, refreshStatus, state, subscribe } from "./js/store.js";
import { renderSidebar } from "./js/sidebar.js";

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

  function render() {
    const route = currentRoute();
    renderSidebar(sidebar, state, route, render);
    mount(main, h("div", { class: "app-column" }, h("h1", { class: "text-h1 app-title" }, viewTitle(route))));
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
  subscribe(render);
  onRoute(render);
  render();
}

start();
