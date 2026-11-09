// The run area under the summary: progress (05), results (06), nothing found (09),
// waiting for a score, interrupted. Fixed copy only; data goes in as text nodes.
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { sourceName } from "./format.js";
import { jobCard } from "./jobcard.js";
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

function cards(matches, ui, handlers) {
  if (!matches.length) return null;
  return h(
    "div",
    { class: "run-cards", role: "listbox", "aria-label": t("results_label") },
    matches.map((m) => jobCard(m, { selected: m.id === ui.selectedId, onOpen: handlers.onOpen })),
  );
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

// view: runView(...). ui: { selectedId, starting, ranking, busyOther, runError, error, busy }.
// handlers: { onSearchAgain, onRank, onWiden(widening), onOpen(match) }
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
          h("p", { class: "text-body" }, view.waiting > 0 ? [t("found", { n: view.found }), " ", t("more_waiting", { m: view.waiting })] : t("found", { n: view.found })),
          view.waiting > 0 ? h("div", { class: "run-actions" }, rank()) : null,
          cards(view.matches, ui, handlers),
          failureLines(view.failures, view.runError),
          h("div", { class: "run-actions" }, again()),
          notices(ui),
        ),
      ];
    case "waiting_only":
      return [
        appLine(
          h("p", { class: "text-body" }, t("waiting_only", { m: view.waiting })),
          failureLines(view.failures, view.runError),
          h("div", { class: "run-actions" }, rank()),
          notices(ui),
        ),
      ];
    case "nothing": {
      const widenings = search.widenings || [];
      return [
        appLine(
          h("p", { class: "text-body" }, t("nothing_found", { n: view.searched, m: view.fetched, what: nothingWhat(search.summary) })),
          failureLines(view.failures, view.runError),
          widenings.length
            ? h(
                "div",
                { class: "run-widen" },
                h("p", { class: "text-body" }, t("widen_intro")),
                h(
                  "div",
                  { class: "conv-chips" },
                  widenings.map((w) => button("secondary conv-chip", widenLabel(w, search.summary), null, () => handlers.onWiden(w), ui.busy || ui.starting)),
                ),
              )
            : null,
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
