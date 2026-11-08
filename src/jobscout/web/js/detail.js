// The job detail panel (screen 07), shared by a search's results and My jobs.
// It sends the verdict itself (PATCH /matches/{id}); the caller decides what the change means
// for its own listing and may answer with a notice ("it no longer shows here").
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { safeUrl, scoreLabel } from "./format.js";
import { companyLine, jobTags, postedAgo } from "./jobcard.js";

function section(title, items, iconName) {
  if (!items || items.length === 0) return null;
  return h(
    "section",
    { class: "dt-section" },
    h("h2", { class: "text-body-sm dt-section__title" }, title),
    h(
      "ul",
      { class: "dt-list" },
      items.map((item) => h("li", { class: "text-body dt-list__item" }, h("span", { class: "dt-list__icon" }, icon(iconName, 16)), h("span", {}, item))),
    ),
  );
}

// host: a persistent <aside class="app-detail">. match: MatchRead.
// opts: { onVerdict(updated) -> notice string | null, onClose() }
// Returns { update(match), close(restoreFocus = true), id }.
export function openDetail(host, match, opts = {}) {
  const opener = document.activeElement;
  let current = match;
  let notice = null;
  let error = null;
  let pending = false;
  let closed = false;

  function onKey(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  async function verdict(status, action) {
    if (pending) return;
    // Save is the only toggle the API knows one way: a saved job cannot be unsaved.
    if (current.status === status) return;
    pending = true;
    error = null;
    draw(action);
    try {
      const updated = await api.patch(`/matches/${current.id}`, { status });
      if (closed) return;
      current = updated;
      notice = opts.onVerdict ? opts.onVerdict(updated) || null : null;
    } catch (e) {
      if (closed) return;
      error = t("request_failed");
    }
    pending = false;
    draw(notice ? "notice-close" : action);
  }

  function draw(focusAction) {
    const job = current.job;
    const score = scoreLabel(current.score);
    const ago = postedAgo(job);
    const url = safeUrl(job.url);
    const saved = current.status === "saved";
    const title = h("h1", { class: "text-h1 dt-title", tabindex: "-1" }, job.title);
    const actions = [];
    if (url) {
      actions.push(
        h(
          "a",
          { class: "js-btn js-btn--primary dt-open", href: url, target: "_blank", rel: "noopener noreferrer", "data-action": "open" },
          t("open_posting"),
          icon("external-link", 16),
        ),
      );
    }
    actions.push(
      h(
        "button",
        { class: "js-btn js-btn--secondary", type: "button", "aria-pressed": saved ? "true" : "false", disabled: pending, "data-action": "save", onclick: () => verdict("saved", "save") },
        icon(saved ? "bookmark-filled" : "bookmark", 16),
        t(saved ? "saved" : "save"),
      ),
    );
    mount(
      host,
      h(
        "div",
        { class: "dt-body" },
        h("div", { class: "dt-head" }, title, h("button", { class: "js-btn js-btn--ghost dt-close", type: "button", "aria-label": t("close"), onclick: () => close() }, icon("x", 20))),
        job.company || job.location ? h("p", { class: "text-body-sm dt-company" }, companyLine(job)) : null,
        jobTags(job),
        score || ago
          ? h(
              "div",
              { class: "dt-score" },
              score ? h("span", { class: "js-tag js-tag--match" }, score) : null,
              h("span", { class: "text-meta dt-score__label" }, [t("fit_score"), ago].filter(Boolean).join(" · ")),
            )
          : null,
        current.reasoning ? h("p", { class: "text-body dt-reasoning" }, current.reasoning) : null,
        section(t("matches_heading"), current.matched_skills, "check"),
        section(t("missing"), current.missing_skills, "minus"),
        section(t("watch_out"), current.red_flags, "alert-triangle"),
      ),
      h(
        "div",
        { class: "dt-foot" },
        notice
          ? h(
              "div",
              { class: "dt-notice", role: "status" },
              h("p", { class: "text-body-sm dt-notice__text" }, notice),
              h("button", { class: "js-btn js-btn--secondary", type: "button", "data-action": "notice-close", onclick: () => close() }, t("close")),
            )
          : null,
        error ? h("p", { class: "text-body-sm dt-error", role: "alert" }, error) : null,
        h("div", { class: "dt-actions" }, actions),
        h(
          "div",
          { class: "dt-actions dt-actions--quiet" },
          h(
            "button",
            { class: "js-btn js-btn--ghost", type: "button", disabled: pending || current.status === "applied", "data-action": "applied", onclick: () => verdict("applied", "applied") },
            icon("check-circle", 16),
            t("mark_applied"),
          ),
          h(
            "button",
            { class: "js-btn js-btn--ghost", type: "button", disabled: pending || current.status === "dismissed", "data-action": "dismiss", onclick: () => verdict("dismissed", "dismiss") },
            icon("eye-off", 16),
            t("dismiss"),
          ),
        ),
      ),
    );
    const target = focusAction ? host.querySelector(`[data-action="${focusAction}"]`) : title;
    if (target && !target.disabled) target.focus();
    else if (focusAction) title.focus();
  }

  function close(restoreFocus = true) {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKey);
    host.hidden = true;
    mount(host);
    if (opts.onClose) opts.onClose();
    if (restoreFocus && opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
  }

  document.addEventListener("keydown", onKey);
  host.hidden = false;
  draw(null);

  return {
    update(next) {
      if (closed) return;
      current = next;
      notice = null;
      error = null;
      draw(null);
    },
    close,
    get id() {
      return current.id;
    },
  };
}
