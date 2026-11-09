// The design system's JobCard, shared by a search's results and My jobs.
// Data goes in as text nodes only; tags come from the job's own fields, never invented.
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { currentLocale, t } from "./i18n.js";
import { salary, scoreLabel, sourceName, timeAgo } from "./format.js";

export function workMode(job) {
  return job.work_mode || (job.remote ? "remote" : null);
}

export function companyLine(job) {
  return [job.company, job.location].filter(Boolean).join(" · ");
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

// match: MatchRead. opts: { selected, onOpen(match), searches: [{id, title}] (My jobs only) }
export function jobCard(match, { selected = false, onOpen, searches = null } = {}) {
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
      "data-match-id": match.id,
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
      h("div", { class: "jc-head" }, h("h3", { class: "js-card__title" }, job.title), h("p", { class: "js-card__company" }, companyLine(job))),
      score ? h("span", { class: "js-tag js-tag--match" }, score) : null,
    ),
    h("div", { class: "jc-foot" }, h("div", { class: "jc-tags" }, jobTags(job), verdictTag(match.status)), meta ? h("span", { class: "js-meta jc-meta" }, meta) : null),
  );
}
