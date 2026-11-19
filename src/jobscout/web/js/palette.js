// The search palette (Ctrl K, or the magnifier in the sidebar): a local search over the titles
// of the searches and the saved jobs. Arrow keys move, Enter opens, Escape or Ctrl K closes.
// It lives on <body>, like the delete dialog, so a sidebar redraw never tears it down.
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { scoreLabel } from "./format.js";

const LIMIT = 5;

// Lower case, without accents, so "junior" finds "Júnior". Pure.
export function fold(text) {
  return String(text || "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

// The groups to show for a query: searches by title, saved jobs by title or company, five
// each, empty groups dropped. searches: SearchListItem[]; saved: MyJobRead[]. Pure.
export function paletteResults(query, searches, saved) {
  const q = fold(String(query || "").trim());
  const hit = (text) => !q || fold(text).includes(q);
  const found = (searches || [])
    .filter((s) => hit(s.title))
    .slice(0, LIMIT)
    .map((s) => ({ kind: "search", id: s.id, title: s.title, count: s.match_count || 0, href: `#/search/${s.id}` }));
  const jobs = (saved || [])
    .filter((item) => hit(`${item.match.job.title} ${item.match.job.company || ""}`))
    .slice(0, LIMIT)
    .map((item) => ({
      kind: "saved",
      id: item.match.id,
      title: [item.match.job.title, item.match.job.company].filter(Boolean).join(" · "),
      score: item.match.score,
      href: `#/my-jobs?tab=saved&open=${item.match.id}`,
    }));
  return [
    { name: "searches", items: found },
    { name: "saved", items: jobs },
  ].filter((g) => g.items.length);
}

let dialog = null;

// getSearches: () => the sidebar's current list.
export function togglePalette(getSearches) {
  if (dialog) dialog.close();
  else openPalette(getSearches());
}

function openPalette(searches) {
  let saved = [];
  let query = "";
  let active = 0;
  let items = [];

  const list = h("div", { class: "pal-list", id: "pal-list", role: "listbox", "aria-label": t("search_palette") });

  function go(item) {
    if (!item) return;
    location.hash = item.href;
    dialog.close();
  }

  function onKey(event) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!items.length) return;
      active = (active + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      draw();
      const option = list.querySelector(`#pal-opt-${active}`);
      if (option && typeof option.scrollIntoView === "function") option.scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(items[active]);
    }
  }

  const input = h("input", {
    class: "pal-input text-body",
    type: "text",
    placeholder: t("palette_placeholder"),
    "aria-label": t("search_palette"),
    role: "combobox",
    "aria-expanded": "true",
    "aria-controls": "pal-list",
    "aria-autocomplete": "list",
    autocomplete: "off",
    spellcheck: "false",
    oninput: (event) => {
      query = event.target.value;
      active = 0;
      draw();
    },
    onkeydown: onKey,
  });

  function option(item, n) {
    const on = n === active;
    const meta = item.kind === "search" ? t("n_jobs", { n: item.count }) : scoreLabel(item.score);
    return h(
      "a",
      {
        class: "pal-item",
        id: `pal-opt-${n}`,
        role: "option",
        href: item.href,
        tabindex: "-1",
        "aria-selected": on ? "true" : "false",
        onclick: () => dialog.close(),
        onmousemove: () => {
          if (active !== n) {
            active = n;
            draw();
          }
        },
      },
      h("span", { class: "pal-item__icon" }, icon(item.kind === "search" ? "message-square" : "bookmark", 16)),
      h("span", { class: "text-body-sm pal-item__title" }, item.title),
      meta ? h("span", { class: "text-meta pal-item__meta" }, meta) : null,
      h("span", { class: "pal-item__enter" }, on ? icon("corner-down-left", 14) : null),
    );
  }

  function draw() {
    const groups = paletteResults(query, searches, saved);
    items = groups.flatMap((g) => g.items);
    if (active >= items.length) active = 0;
    let n = 0;
    mount(
      list,
      groups.length
        ? groups.map((g) => [h("p", { class: "text-meta pal-group" }, t(`palette_${g.name}`)), g.items.map((item) => option(item, n++))])
        : h("p", { class: "text-body-sm pal-empty" }, t("palette_empty")),
    );
    if (items.length) input.setAttribute("aria-activedescendant", `pal-opt-${active}`);
    else input.removeAttribute("aria-activedescendant");
  }

  dialog = h(
    "dialog",
    {
      class: "pal",
      "aria-label": t("search_palette"),
      // A click on the backdrop lands on the dialog itself: close.
      onclick: (event) => {
        if (event.target === dialog) dialog.close();
      },
      onclose: () => {
        dialog.remove();
        dialog = null;
      },
    },
    h("div", { class: "pal-head" }, icon("search", 18), input, h("kbd", { class: "text-meta pal-kbd" }, "esc")),
    list,
    h(
      "div",
      { class: "text-meta pal-foot", "aria-hidden": "true" },
      h("span", {}, `↑↓ ${t("palette_nav")}`),
      h("span", {}, `↵ ${t("palette_open")}`),
      h("span", {}, `ctrl k ${t("palette_toggle")}`),
    ),
  );
  document.body.appendChild(dialog);
  dialog.showModal();
  input.focus();
  draw();
  api
    .get("/my-jobs?tab=saved")
    .then((data) => {
      if (!dialog) return;
      saved = data.items;
      draw();
    })
    .catch(() => {});
}
