// The job detail panel (screen 07), shared by a search's results and My jobs.
// It sends the verdict itself (PATCH /matches/{id}); the caller decides what the change means
// for its own listing and may answer with a notice ("it no longer shows here").
// Every verdict can be taken back: a pressed button sends "new", and a notice offers Undo.
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
// The statuses the user can set; anything else (the pipeline's own) comes back as "new".
const USER_STATUSES = new Set(["saved", "dismissed", "applied"]);

// What a click on a verdict button sends: the verdict, or "new" when it is already on.
export function nextStatus(current, verdict) {
  return current === verdict ? "new" : verdict;
}

// The status Undo restores after a verdict changed `before` into something else.
export function undoStatus(before) {
  return USER_STATUSES.has(before) ? before : "new";
}

// Returns { update(match, {focus}), close(restoreFocus = true), id, match }.
export function openDetail(host, match, opts = {}) {
  const opener = document.activeElement;
  let current = match;
  let notice = null;
  let error = null;
  let pending = false;
  let closed = false;
  let undoTo = null;

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
    if (pending || current.status === status) return;
    const before = current.status;
    pending = true;
    error = null;
    draw(action);
    try {
      const updated = await api.patch(`/matches/${current.id}`, { status });
      if (closed) return;
      current = updated;
      notice = opts.onVerdict ? opts.onVerdict(updated) || null : null;
      // Undo is offered with the notice, which is when the job has left the caller's list.
      undoTo = notice && action !== "undo" ? undoStatus(before) : null;
    } catch (e) {
      if (closed) return;
      error = t("request_failed");
    }
    pending = false;
    draw(notice ? (undoTo ? "undo" : "notice-close") : action);
  }

  function draw(focusAction) {
    const job = current.job;
    const score = scoreLabel(current.score);
    const ago = postedAgo(job);
    const url = safeUrl(job.url);
    const status = current.status;
    const saved = status === "saved";
    const applied = status === "applied";
    const dismissed = status === "dismissed";
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
        // A pressed verdict button takes the verdict back on the next click.
        {
          class: "js-btn js-btn--secondary dt-toggle",
          type: "button",
          disabled: pending,
          "aria-pressed": saved ? "true" : "false",
          "data-action": "save",
          onclick: () => verdict(nextStatus(status, "saved"), "save"),
        },
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
              undoTo
                ? h(
                    "button",
                    { class: "js-btn js-btn--secondary", type: "button", disabled: pending, "data-action": "undo", onclick: () => verdict(undoTo, "undo") },
                    icon("rotate-ccw", 16),
                    t("undo"),
                  )
                : null,
              h("button", { class: "js-btn js-btn--ghost", type: "button", "data-action": "notice-close", onclick: () => close() }, t("close")),
            )
          : null,
        error ? h("p", { class: "text-body-sm dt-error", role: "alert" }, error) : null,
        h("div", { class: "dt-actions" }, actions),
        h(
          "div",
          { class: "dt-actions dt-actions--quiet" },
          h(
            "button",
            {
              class: "js-btn js-btn--ghost dt-toggle",
              type: "button",
              disabled: pending,
              "aria-pressed": applied ? "true" : "false",
              "data-action": "applied",
              onclick: () => verdict(nextStatus(status, "applied"), "applied"),
            },
            icon("check-circle", 16),
            t(applied ? "applied" : "mark_applied"),
          ),
          h(
            "button",
            {
              class: "js-btn js-btn--ghost dt-toggle",
              type: "button",
              disabled: pending,
              "aria-pressed": dismissed ? "true" : "false",
              "data-action": "dismiss",
              onclick: () => verdict(nextStatus(status, "dismissed"), "dismiss"),
            },
            icon("eye-off", 16),
            t(dismissed ? "dismissed" : "dismiss"),
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
        undoTo = null;
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
