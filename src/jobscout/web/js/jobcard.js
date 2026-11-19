// The design system's JobCard, shared by a search's results and My jobs.
// Data goes in as text nodes only; tags come from the job's own fields, never invented.
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { currentLocale, t } from "./i18n.js";
import { safeUrl, salary, scoreLabel, scoreLevel, sourceName, timeAgo } from "./format.js";

export function workMode(job) {
  return job.work_mode || (job.remote ? "remote" : null);
}

export function companyLine(job) {
  return [job.company, job.location].filter(Boolean).join(" · ");
}

// The letter on the company's square: the company's first letter, or the title's.
export function companyInitial(job) {
  const name = String(job.company || job.title || "").trim();
  return name ? name.charAt(0).toUpperCase() : "·";
}

function httpsUrl(url) {
  if (typeof url !== "string") return null;
  try {
    return new URL(url).protocol === "https:" ? url : null;
  } catch (e) {
    return null;
  }
}

// The company's square: its initial, with the board's logo over it once the logo loads. A logo
// that fails to load hides itself, so the initial is what is left. Decorative: the company's
// name is always written next to it. No referrer, so the board's CDN never sees our page.
export function companyLogo(job, extraClass) {
  const src = httpsUrl(job.company_logo);
  const img = src
    ? h("img", {
        class: "js-card__logo-img",
        alt: "",
        loading: "lazy",
        decoding: "async",
        referrerpolicy: "no-referrer",
        onload: () => img.setAttribute("data-loaded", ""),
        onerror: () => img.setAttribute("hidden", ""),
        src,
      })
    : null;
  return h(
    "span",
    { class: extraClass ? `js-card__logo ${extraClass}` : "js-card__logo", "aria-hidden": "true" },
    companyInitial(job),
    img,
  );
}

export function postedAgo(job) {
  return timeAgo(job.posted_at || job.first_seen_at, new Date(), t);
}

// Source, then REMOTE / HYBRID / ON-SITE; js-tag upper-cases them.
export function jobTags(job) {
  const mode = workMode(job);
  return h(
    "div",
    { class: "js-card__tags" },
    h("span", { class: "js-tag" }, sourceName(job.source)),
    mode ? h("span", { class: "js-tag" }, t(`mode_${mode}`)) : null,
  );
}

// The user's verdict, as a word with its icon (never colour alone).
export function verdictTag(status) {
  if (status === "saved") return h("span", { class: "js-tag" }, icon("bookmark-filled", 12), t("saved"));
  if (status === "applied") return h("span", { class: "js-tag js-tag--success" }, icon("check-circle", 12), t("applied"));
  return null;
}

// What identifies a card on the page: the match id, or the job's for a job with no score.
export function cardKey(match) {
  return match.id === null || match.id === undefined ? `job-${match.job.id}` : String(match.id);
}

// match: MatchRead. opts: { selected, onOpen(match), searches: [{id, title}] (My jobs only),
// excerpt (the LLM's reasoning under the title, for the best three), unscored ("No score" tag) }
export function jobCard(match, { selected = false, onOpen, searches = null, excerpt = false, unscored = false } = {}) {
  const job = match.job;
  const score = scoreLabel(match.score);
  const named = searches && searches.length ? searches.map((s) => s.title).join(", ") : null;
  const meta = [salary(job, currentLocale()), postedAgo(job), named].filter(Boolean).join(" · ");
  const open = () => {
    if (onOpen) onOpen(match);
  };
  return h(
    "article",
    {
      class: "js-card jc",
      role: "option",
      tabindex: "0",
      "aria-selected": selected ? "true" : "false",
      "data-match-id": cardKey(match),
      onclick: open,
      onkeydown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      },
    },
    h(
      "div",
      { class: "js-card__top" },
      companyLogo(job),
      h(
        "div",
        { class: "jc-head" },
        job.company ? h("p", { class: "text-label jc-company" }, job.company) : null,
        job.location ? h("p", { class: "js-card__company" }, job.location) : null,
      ),
      score ? h("span", { class: "js-tag js-tag--match", "data-level": scoreLevel(match.score) }, score) : null,
      !score && unscored ? h("span", { class: "js-tag" }, t("no_score")) : null,
    ),
    h("h3", { class: "js-card__title" }, job.title),
    excerpt && match.reasoning ? h("p", { class: "text-body-sm jc-reason" }, match.reasoning) : null,
    h("div", { class: "jc-foot" }, h("div", { class: "jc-tags" }, jobTags(job), verdictTag(match.status)), meta ? h("span", { class: "js-meta jc-meta" }, meta) : null),
  );
}

// The columns of My jobs' table, in order. The header and every row share them.
export const ROW_COLUMNS = ["job", "fit", "source", "status", "search", "date"];

export function jobRowHeader() {
  return h(
    "div",
    { class: "jr jr--head", "aria-hidden": "true" },
    ROW_COLUMNS.map((c) => h("span", { class: `text-meta jr__${c}` }, t(`col_${c}`))),
  );
}

// My jobs' row: the same job as the card, laid out in the table's columns.
// opts: { selected, onOpen(match), searches: [{id, title}], onSave(match) }
// With onSave, hovering the row (or focusing in it) swaps the date for Save and Open original.
export function jobRow(match, { selected = false, onOpen, searches = null, onSave = null } = {}) {
  const job = match.job;
  const score = scoreLabel(match.score);
  const status = ["saved", "applied", "dismissed"].includes(match.status) ? match.status : "new";
  const url = safeUrl(job.url);
  const saved = match.status === "saved";
  const stop = (event) => event.stopPropagation();
  const actions = onSave
    ? h(
        "div",
        { class: "jr__actions", onclick: stop, onkeydown: stop },
        h(
          "button",
          {
            class: `js-btn js-btn--ghost js-icon-btn js-icon-btn--sm jr__save`,
            type: "button",
            "aria-pressed": saved ? "true" : "false",
            "aria-label": `${t(saved ? "saved" : "save")}: ${job.title}`,
            title: t(saved ? "saved" : "save"),
            onclick: () => onSave(match),
          },
          icon(saved ? "bookmark-check" : "bookmark", 16),
        ),
        url
          ? h(
              "a",
              { class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--sm", href: url, target: "_blank", rel: "noopener noreferrer", "aria-label": `${t("open_posting")}: ${job.title}`, title: t("open_posting") },
              icon("external-link", 16),
            )
          : null,
      )
    : null;
  const where = [job.company, job.location, salary(job, currentLocale())].filter(Boolean).join(" · ");
  const open = () => {
    if (onOpen) onOpen(match);
  };
  return h(
    "article",
    {
      class: "jr",
      role: "option",
      tabindex: "0",
      "aria-selected": selected ? "true" : "false",
      "data-match-id": cardKey(match),
      onclick: open,
      onkeydown: (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      },
    },
    h(
      "div",
      { class: "jr__job" },
      companyLogo(job),
      h("div", { class: "jr__text" }, h("h3", { class: "text-label jr__title" }, job.title), where ? h("p", { class: "text-body-sm jr__where" }, where) : null),
    ),
    h("div", { class: "jr__fit" }, score ? h("span", { class: "js-tag js-tag--match", "data-level": scoreLevel(match.score) }, score) : null),
    h("div", { class: "jr__source" }, h("span", { class: "js-tag" }, sourceName(job.source))),
    h("div", { class: `text-body-sm jr__status jr__status--${status}` }, h("span", { class: "jr__dot", "aria-hidden": "true" }), t(status === "new" ? "status_new" : status)),
    h("div", { class: "text-body-sm jr__search" }, searches && searches.length ? searches.map((s) => s.title).join(", ") : ""),
    h("div", { class: "jr__end" }, h("span", { class: "js-meta jr__date" }, postedAgo(job) || ""), actions),
  );
}
