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

function isEditable(el) {
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable === true;
}

// host: a persistent <aside class="app-detail">. match: MatchRead.
// opts: { onVerdict(updated) -> notice string | null, onClose() }
// Returns { update(match, {focus}), close(restoreFocus = true), id, match }.
export function openDetail(host, match, opts = {}) {
  const opener = document.activeElement;
  let current = match;
  let notice = null;
  let error = null;
  let pending = false;
  let closed = false;

  // Escape closes the panel from inside it, or from anywhere but a field being typed in.
  function onKey(event) {
    if (event.key !== "Escape") return;
    const target = event.target;
    const inside = target && typeof host.contains === "function" && host.contains(target);
    if (!inside && isEditable(target)) return;
    event.preventDefault();
    close();
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
        // The API cannot unsave: once saved, the button stays as a disabled "Saved".
        { class: "js-btn js-btn--secondary", type: "button", disabled: pending || saved, "data-action": "save", onclick: () => verdict("saved", "save") },
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
    if (focusAction === "none") return;
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
    // focus: false redraws in place (a poll), keeping focus on the same action if it was in here.
    update(next, { focus = true } = {}) {
      if (closed) return;
      let keep = "none";
      if (!focus) {
        const active = document.activeElement;
        if (active && host.contains(active)) keep = active.getAttribute("data-action") || null;
      } else {
        notice = null;
        error = null;
      }
      current = next;
      draw(focus ? null : keep);
    },
    close,
    get id() {
      return current.id;
    },
    get match() {
      return current;
    },
  };
}
