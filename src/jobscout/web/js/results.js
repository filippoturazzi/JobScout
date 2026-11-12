// The run area under the summary: progress (05), results (06), nothing found (09),
// waiting for a score, interrupted. Fixed copy only; data goes in as text nodes.
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { sourceName } from "./format.js";
import { cardKey, jobCard } from "./jobcard.js";
import { resultsLayout } from "./resultslayout.js";
import { runHeadline } from "./runview.js";
import { appLine } from "./conversation.js";

const SOURCE_ICONS = { done: "check-circle", searching: "loader", waiting: "clock", failed: "alert-triangle", skipped: "minus" };

function sourceState(s) {
  if (s.state === "done") return t("src_done", { n: s.fetched || 0 });
  if (s.state === "searching") {
    const total = Math.max(s.queries_total || 0, 1);
    return t("src_searching", { i: Math.min((s.queries_done || 0) + 1, total), n: total });
  }
  return t(`src_${s.state}`);
}

function sourceRows(sources) {
  return h(
    "ul",
    { class: "run-sources" },
    sources.map((s) =>
      h(
        "li",
        { class: `run-src run-src--${s.state}` },
        h("span", { class: "run-src__icon" }, icon(SOURCE_ICONS[s.state] || "clock", 16)),
        h("span", { class: "text-meta run-src__name" }, sourceName(s.name)),
        h("span", { class: "text-meta run-src__state" }, sourceState(s)),
      ),
    ),
  );
}

function scoring(progress) {
  if (progress.toScore <= 0) return null;
  const text = t("scoring", { done: Math.min(progress.scored, progress.toScore), total: progress.toScore });
  return h(
    "div",
    { class: "run-progress" },
    h("progress", { class: "run-bar", max: progress.toScore, value: Math.min(progress.scored, progress.toScore), "aria-label": text }),
    h("p", { class: "text-meta run-progress__text" }, text),
  );
}

function failureLine(iconName, text) {
  return h("li", { class: "text-body-sm run-failure" }, h("span", { class: "run-failure__icon" }, icon(iconName, 16)), h("span", {}, text));
}

const FAILURE_ICONS = { skipped: "minus", note: "info", failed: "alert-triangle" };

// One line per source that failed or was skipped and per note a source left, then the run's own
// error if it ended on one. A note ("Indeed: not searched in Spain, …") is not a failure: it
// reads "{source}: {detail}", like a skip, never "did not answer".
export function failureLines(failures, runError = null) {
  if (!failures.length && !runError) return null;
  return h(
    "ul",
    { class: "run-failures" },
    runError ? failureLine("alert-triangle", t("run_failed", { detail: runError })) : null,
    failures.map((f) =>
      failureLine(
        FAILURE_ICONS[f.kind] || "alert-triangle",
        f.kind === "failed"
          ? t("source_failed_line", { source: sourceName(f.name), detail: f.detail })
          : t("source_skipped_line", { source: sourceName(f.name), detail: f.detail }),
      ),
    ),
  );
}

// An unscored job (UnscoredRead) in the shape the cards and the detail panel read.
export function asMatch(item) {
  return {
    id: null,
    score: null,
    reasoning: null,
    matched_skills: [],
    missing_skills: [],
    red_flags: [],
    status: "new",
    similarity: item.similarity,
    job: item.job,
    unscored: true,
  };
}

function card(m, ui, handlers, opts = {}) {
  return jobCard(m, { selected: cardKey(m) === ui.selectedId, onOpen: handlers.onOpen, ...opts });
}

function grid(label, cards, extra = "") {
  if (!cards.length) return null;
  return h("div", { class: `run-grid${extra}`, role: "listbox", "aria-label": label }, cards);
}

function cards(matches, ui, handlers) {
  return grid(t("results_label"), matches.map((m) => card(m, ui, handlers)));
}

function pager(layout, handlers) {
  if (layout.pages <= 1) return null;
  const go = (n) => () => handlers.onPage(n);
  const numbers = [];
  for (let n = 1; n <= layout.pages; n++) {
    numbers.push(
      h(
        "button",
        { class: "js-btn js-btn--ghost run-pager__btn", type: "button", "aria-label": t("page_n", { n }), "aria-current": n === layout.page ? "page" : null, onclick: go(n) },
        String(n),
      ),
    );
  }
  return h(
    "nav",
    { class: "run-pager", "aria-label": t("pages") },
    h("button", { class: "js-btn js-btn--ghost run-pager__btn", type: "button", "aria-label": t("page_prev"), disabled: layout.page <= 1, onclick: go(layout.page - 1) }, icon("chevron-left", 16)),
    numbers,
    h("button", { class: "js-btn js-btn--ghost run-pager__btn", type: "button", "aria-label": t("page_next"), disabled: layout.page >= layout.pages, onclick: go(layout.page + 1) }, icon("chevron-right", 16)),
  );
}

// "Rank the rest", with how many it would score. Shown only while there is something to score.
function rankLine(view, rank) {
  if (view.waiting <= 0) return null;
  return h("div", { class: "run-actions run-rank" }, h("span", { class: "text-meta" }, t("can_score", { m: view.waiting })), rank());
}

function resultsBody(view, ui, handlers, rank) {
  const layout = resultsLayout(view.matches, view.unscored, ui.page || 1);
  const split = layout.items.findIndex((it) => it.kind === "divider");
  const scored = split === -1 ? layout.items : layout.items.slice(0, split);
  const loose = split === -1 ? [] : layout.items.slice(split + 1);
  return [
    layout.highlighted.length
      ? h(
          "section",
          { class: "run-best" },
          h("p", { class: "text-meta run-best__label" }, t("best_for_you")),
          grid(t("best_for_you"), layout.highlighted.map((m) => card(m, ui, handlers, { excerpt: true })), " run-grid--top"),
        )
      : null,
    grid(t("results_label"), scored.map((it) => card(it.match, ui, handlers))),
    split !== -1
      ? h(
          "div",
          { class: "run-divider" },
          h("p", { class: "text-body run-divider__title" }, t("unscored_divider", { n: view.unscored.length })),
          rankLine(view, rank),
        )
      : null,
    grid(t("unscored_divider", { n: view.unscored.length }), loose.map((it) => card(asMatch(it.item), ui, handlers, { unscored: true }))),
    pager(layout, handlers),
  ];
}

// "on-site junior roles in Recife", built from the summary: work mode, level, place.
export function nothingWhat(summary) {
  const s = summary || {};
  const mode = (s.work_modes || []).map((m) => t(`what_mode_${m}`)).join(` ${t("or")} `);
  const level = s.level && s.level !== "any" ? t(`what_level_${s.level}`) : "";
  let place = "";
  if (s.abroad_from) place = t("place_abroad", { country: s.abroad_from });
  else if (s.city || s.country) place = t("place_in", { place: s.city || s.country });
  if (!mode && !level && !place) return t("what_any");
  const roles = t("what_roles", { mode, level }).replace(/\s+/g, " ").trim();
  return [roles, place].filter(Boolean).join(" ");
}

function widenLabel(w, summary) {
  if (w.id === "whole_country") return t("widen_whole_country", { country: (summary && summary.country) || "" });
  return t(`widen_${w.id}`);
}

function button(kind, label, iconName, onclick, disabled) {
  return h("button", { class: `js-btn js-btn--${kind}`, type: "button", disabled, onclick }, iconName ? icon(iconName, 16) : null, label);
}

// The 409 "another search is running" line, the run's own failure to start, a widening's error.
function notices(ui) {
  const out = [];
  if (ui.busyOther !== null && ui.busyOther !== undefined) {
    out.push(
      h(
        "p",
        { class: "text-body-sm run-notice", role: "status" },
        icon("info", 16),
        h("a", { class: "run-notice__link", href: `#/search/${ui.busyOther}` }, t("search_busy")),
      ),
    );
  }
  if (ui.runError) out.push(h("p", { class: "text-body-sm conv-error", role: "alert" }, ui.runError));
  if (ui.error && ui.error.qid === "widen") out.push(h("p", { class: "text-body-sm conv-error", role: "alert" }, ui.error.text));
  return out;
}

function widenBlock(search, ui, handlers) {
  const widenings = search.widenings || [];
  if (!widenings.length) return null;
  return h(
    "div",
    { class: "run-widen" },
    h("p", { class: "text-body" }, t("widen_intro")),
    h(
      "div",
      { class: "conv-chips" },
      widenings.map((w) => button("secondary conv-chip", widenLabel(w, search.summary), null, () => handlers.onWiden(w), ui.busy || ui.starting)),
    ),
  );
}

// view: runView(...). ui: { selectedId, page, starting, ranking, busyOther, runError, error, busy }.
// handlers: { onSearchAgain, onRank, onWiden(widening), onOpen(match), onPage(n) }
export function runSection(view, search, ui, handlers) {
  const again = () => button("secondary", t("search_again"), "rotate-ccw", () => handlers.onSearchAgain(), ui.starting);
  const rank = () => button("secondary", t("rank_rest"), null, () => handlers.onRank(), ui.starting);

  switch (view.state) {
    case "running": {
      const headline = runHeadline(view, ui.ranking);
      return [
        appLine(
          h("p", { class: "text-body run-status", "aria-live": "polite" }, t(headline.key, { n: headline.n })),
          headline.showSources ? sourceRows(view.sources) : null,
          scoring(view.progress),
          cards(view.matches, ui, handlers),
        ),
      ];
    }
    case "results":
      return [
        appLine(
          h("p", { class: "text-body" }, view.found > 0 ? t("found", { n: view.found }) : t("none_scored")),
          view.widen ? widenBlock(search, ui, handlers) : null,
          // With nothing unscored to list (old scores waiting to be redone), the rank line has
          // no divider to sit in: it goes under the count, as before.
          view.unscored.length ? null : rankLine(view, rank),
          resultsBody(view, ui, handlers, rank),
          failureLines(view.failures, view.runError),
          h("div", { class: "run-actions" }, again()),
          notices(ui),
        ),
      ];
    case "nothing": {
      return [
        appLine(
          h("p", { class: "text-body" }, t("nothing_found", { n: view.searched, m: view.fetched, what: nothingWhat(search.summary) })),
          failureLines(view.failures, view.runError),
          widenBlock(search, ui, handlers),
          h("div", { class: "run-actions" }, again()),
          notices(ui),
        ),
      ];
    }
    case "interrupted":
      return [appLine(h("p", { class: "text-body" }, t("interrupted")), h("div", { class: "run-actions" }, again()), notices(ui))];
    default:
      // No run yet: only what the summary's "Search jobs" may have to say.
      return notices(ui).length ? [appLine(notices(ui))] : [];
  }
}
