// Renders the transcript entries. Fixed copy only; data goes in as text nodes.
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { sourceName } from "./format.js";

function placePhrase(place) {
  if (!place) return "";
  if (place.kind === "anywhere") return t("place_anywhere");
  if (place.kind === "abroad") return t("place_abroad", { country: place.name });
  return t("place_in", { place: place.name });
}

export function gotitText(what, asking) {
  const parts = [what.role, ...what.skills].filter(Boolean).join(", ");
  const place = placePhrase(what.place);
  const body = [parts, place].filter(Boolean).join(", ");
  return t(asking ? "gotit_asking" : "gotit", { what: body });
}

export function appLine(...content) {
  return h("div", { class: "conv-app" }, h("span", { class: "conv-app__icon" }, icon("search", 24)), h("div", { class: "conv-app__body" }, ...content));
}

function userBubble(text) {
  return h("div", { class: "conv-user" }, h("div", { class: "conv-user__bubble text-body" }, text));
}

export function questionText(qid, country) {
  return t(`q_${qid}`, { country: country || "" });
}

export function optionLabel(qid, option, country) {
  switch (option.choice) {
    case "any":
      return t("dont_mind");
    case "remote":
    case "hybrid":
    case "onsite":
      return t(`mode_${option.choice}`);
    case "intern":
    case "junior":
    case "mid":
    case "senior":
      return t(`level_${option.choice}`);
    case "country":
      return option.value || t("other_country");
    case "abroad":
      return t("abroad_not", { country: option.value || "" });
    case "anywhere":
      return qid === "city" && (option.value || country) ? t("anywhere_in", { country: option.value || country }) : t("anywhere");
    case "other":
      return qid === "city" ? t("other_city") : t("other_country");
    case "skill":
      return option.value || "";
    default:
      return option.choice;
  }
}

// The answer a click on one option sends (null for "other", which asks for typing).
function singleAnswer(option) {
  if (option.choice === "country" || option.choice === "abroad") return { choice: option.choice, values: [option.value] };
  if (option.choice === "other") return null;
  return { choice: option.choice, values: [] };
}

// A question with its chips. opts: { showCounter, primary, error, initial }
function questionBlock(q, country, handlers, opts) {
  const picked = new Set(q.multi && opts.initial && opts.initial.choice === "pick" ? opts.initial.values : []);
  let any = Boolean(q.multi && opts.initial && opts.initial.choice === "any");
  const chips = [];
  const cont = q.multi
    ? h("button", { class: `js-btn ${opts.primary ? "js-btn--primary" : "js-btn--secondary"} conv-continue`, type: "button" }, t("continue"))
    : null;
  const keyOf = (option) => (option.choice === "skill" ? option.value : option.choice);

  function sync() {
    chips.forEach(({ el, option }) => {
      const on = option.choice === "any" ? any : picked.has(keyOf(option));
      el.setAttribute("aria-pressed", String(on));
      el.classList.toggle("is-on", on);
    });
    if (cont) {
      if (!any && picked.size === 0) cont.setAttribute("disabled", "");
      else cont.removeAttribute("disabled");
    }
  }

  for (const option of q.options) {
    const attrs = { class: "js-btn js-btn--secondary conv-chip", type: "button" };
    if (q.multi) attrs["aria-pressed"] = "false";
    const el = h("button", attrs, h("span", { class: "conv-chip__check" }, icon("check", 14)), optionLabel(q.id, option, country));
    el.addEventListener("click", () => {
      if (q.multi) {
        if (option.choice === "any") {
          any = !any;
          picked.clear();
        } else {
          any = false;
          if (picked.has(keyOf(option))) picked.delete(keyOf(option));
          else picked.add(keyOf(option));
        }
        sync();
        return;
      }
      const answer = singleAnswer(option);
      if (answer === null) handlers.onOther(q.id);
      else handlers.onAnswer(q.id, answer);
    });
    chips.push({ el, option });
  }
  if (cont) {
    cont.addEventListener("click", () => {
      handlers.onAnswer(q.id, any ? { choice: "any", values: [] } : { choice: "pick", values: [...picked] });
    });
  }
  sync();

  return h(
    "div",
    { class: "conv-question" },
    opts.showCounter && q.total ? h("p", { class: "text-meta conv-counter" }, t("counter", { n: q.position, total: q.total })) : null,
    appLine(
      h("p", { class: "text-body conv-question__text" }, questionText(q.id, country)),
      q.options.length ? h("div", { class: "conv-chips", role: q.multi ? "group" : null, "aria-label": questionText(q.id, country) }, chips.map((c) => c.el)) : null,
      cont ? h("div", { class: "conv-continue-row" }, cont) : null,
      opts.error ? h("p", { class: "text-body-sm conv-error", role: "alert" }, opts.error) : null,
    ),
  );
}

function pastQuestion(qid, country) {
  return h("div", { class: "conv-question conv-question--past" }, appLine(h("p", { class: "text-body conv-question__text" }, questionText(qid, country))));
}

function tags(values) {
  return h("div", { class: "conv-tags" }, values.map((v) => h("span", { class: "js-tag" }, v)));
}

export function locationRow(summary) {
  if (summary.abroad_from) return t("not_country", { country: summary.abroad_from });
  return summary.city || summary.country || t("anywhere");
}

// The question the Location row edits: the deepest one that applies.
export function locationQuestionId(search) {
  const a = search.answers || {};
  const s = search.summary || {};
  if (s.city || a.city || (search.asked || []).includes("city")) return "city";
  if (a.country || (search.asked || []).includes("country")) return "country";
  return "location";
}

// "Search jobs" before the first run; a disabled "Searching…" while one runs; after that the
// run area below carries "Search again", so the summary has no button.
function searchButton(ui, handlers) {
  if (ui.runState === "running" || (ui.starting && ui.runState === "none")) {
    return h("button", { class: "js-btn js-btn--secondary conv-searching", type: "button", disabled: true }, h("span", { class: "spin" }, icon("loader", 16)), t("searching"));
  }
  if (ui.runState && ui.runState !== "none") return null;
  return h("button", { class: "js-btn js-btn--primary", type: "button", onclick: () => handlers.onRun() }, t("search_jobs"));
}

function summaryCard(search, ui, handlers) {
  const s = search.summary;
  const rows = [
    ["role", t("row_role"), s.terms.length ? s.terms : s.role ? [s.role] : [], "role"],
    ["level", t("row_level"), [s.level && s.level !== "any" ? t(`level_${s.level}`) : t("dont_mind")], "level"],
    ["work_modes", t("row_work_mode"), s.work_modes.length ? s.work_modes.map((m) => t(`mode_${m}`)) : [t("dont_mind")], "work_modes"],
    ["location", t("row_location"), [locationRow(s)], locationQuestionId(search)],
  ];
  if (s.skills.length) rows.push(["skills", t("row_skills"), s.skills, "skills"]);
  const names = (ui.sources || []).map(sourceName);
  return h(
    "div",
    { class: "conv-card js-pref" },
    rows.map(([key, label, values, qid]) =>
      h(
        "div",
        { class: "conv-row", "data-row": key },
        h("span", { class: "text-body-sm conv-row__label" }, label),
        tags(values),
        h("button", { class: "js-btn js-btn--ghost conv-row__edit", type: "button", "aria-label": t("edit_row", { row: label }), onclick: () => handlers.onEdit(qid) }, icon("pencil", 16)),
      ),
    ),
    h(
      "div",
      { class: "conv-card__foot" },
      h("span", { class: "text-meta conv-sources" }, t("sources_line", { n: names.length, names: names.join(", ") })),
      searchButton(ui, handlers),
    ),
  );
}

// ui: { sources: [name], editing: Question | null, error: {qid, text} | null, reading: bool,
//       runState: runView state, starting: bool }
export function renderEntries(entries, search, ui, handlers) {
  const country = (search.summary || {}).country || null;
  const out = [];
  for (const entry of entries) {
    if (entry.kind === "user") out.push(userBubble(entry.text));
    else if (entry.kind === "gotit") out.push(appLine(h("p", { class: "text-body" }, gotitText(entry.what, entry.asking))));
    else if (entry.kind === "error") {
      out.push(
        h(
          "div",
          { class: "conv-failure", role: "alert" },
          icon("alert-triangle", 20),
          h("p", { class: "text-body conv-failure__text" }, entry.text),
          h("button", { class: "js-btn js-btn--secondary", type: "button", disabled: ui.reading, onclick: () => handlers.onReread() }, t("try_again")),
        ),
      );
    } else if (entry.kind === "question") {
      if (entry.active) {
        const error = ui.error && ui.error.qid === entry.question.id ? ui.error.text : null;
        out.push(questionBlock(entry.question, country, handlers, { showCounter: true, primary: true, error }));
      } else out.push(pastQuestion(entry.question.id, country));
    } else if (entry.kind === "summary") {
      out.push(appLine(h("p", { class: "text-body" }, t("summary_intro"))));
      out.push(h("div", { class: "conv-summary" }, summaryCard(search, ui, handlers)));
      if (ui.editing) {
        const q = ui.editing;
        const error = ui.error && ui.error.qid === q.id ? ui.error.text : null;
        out.push(h("div", { class: "conv-edit" }, questionBlock(q, country, handlers, { showCounter: false, primary: false, initial: (search.answers || {})[q.id], error })));
      }
    }
  }
  return out;
}
