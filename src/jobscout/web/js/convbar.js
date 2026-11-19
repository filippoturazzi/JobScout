// The search page's top bar: the conversation's title, its job count and a "⋯" menu with
// Rename (the title turns into a field in place), Export CSV and Delete.
// Enter or leaving the field saves; Escape puts the title back.
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { toggleMenu } from "./popover.js";

export const TITLE_MAX = 120; // pipeline/searches.py TITLE_MAX

// The title to send: spaces collapsed, or null when it is blank or unchanged. Pure.
export function cleanTitle(text, current) {
  const clean = String(text || "").split(/\s+/).filter(Boolean).join(" ");
  if (!clean || clean === current) return null;
  return clean;
}

// handlers: { onRename(text) -> Promise, onExport(), onDelete() }
export function convBar(search, count, handlers) {
  let current = search;
  let jobs = count;
  let input = null; // the field while renaming

  const el = h("header", { class: "conv-bar" });
  const more = h(
    "button",
    {
      class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--sm conv-bar__more",
      type: "button",
      "aria-label": t("conversation_actions"),
      title: t("conversation_actions"),
      "aria-haspopup": "menu",
      "aria-expanded": "false",
      onclick: () =>
        toggleMenu(more, t("conversation_actions"), [
          { label: t("rename"), icon: "pencil", run: startRename },
          { label: t("export_csv"), icon: "download", run: () => handlers.onExport() },
          { label: t("delete"), icon: "trash", danger: true, run: () => handlers.onDelete() },
        ]),
    },
    icon("ellipsis", 18),
  );

  function finish(save) {
    if (!input) return;
    const field = input;
    input = null;
    const text = save ? cleanTitle(field.value, current.title) : null;
    draw();
    if (text) {
      // Shown at once; the page redraws with what the server kept, or puts it back on failure.
      const before = current;
      current = { ...current, title: text };
      draw();
      Promise.resolve(handlers.onRename(text)).catch(() => {
        current = before;
        draw();
      });
    }
    more.focus();
  }

  function startRename() {
    if (input) return;
    input = h("input", {
      class: "text-h2 conv-bar__input",
      type: "text",
      maxlength: TITLE_MAX,
      "aria-label": t("rename"),
      onkeydown: (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(true);
        } else if (event.key === "Escape") {
          // Escape here belongs to the field, not the panel or the page.
          event.preventDefault();
          event.stopPropagation();
          finish(false);
        }
      },
      onblur: () => finish(true),
    });
    input.value = current.title;
    draw();
    input.focus();
    if (typeof input.select === "function") input.select();
  }

  // The count and the menu are built once and never moved, so a redraw keeps the focus on "⋯".
  const titleSlot = h("div", { class: "conv-bar__slot" });
  const countEl = h("span", { class: "text-meta conv-bar__count" });
  mount(el, titleSlot, countEl, h("div", { class: "conv-bar__menu" }, more));

  function draw() {
    mount(titleSlot, input || h("h1", { class: "text-h2 conv-bar__title", title: current.title }, current.title));
    countEl.setAttribute("data-count", String(jobs));
    mount(countEl, t("n_jobs", { n: jobs }));
  }

  draw();
  return {
    el,
    startRename,
    // A new SearchRead or count from the page; a rename in progress keeps its field.
    update(next, n) {
      current = next;
      jobs = n;
      if (!input) draw();
    },
  };
}
