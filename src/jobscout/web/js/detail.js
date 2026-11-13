// The job detail panel (screen 07), shared by a search's results and My jobs.
// It sends the verdict itself (PATCH /matches/{id}); the caller decides what the change means
// for its own listing and may answer with a notice ("it no longer shows here").
// Every verdict can be taken back: a pressed button sends "new", and its toast offers Undo,
// which still works after the panel has closed.
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { api } from "./api.js";
import { showToast } from "./toast.js";
import { safeUrl, scoreLabel, scoreLevel, sourceName } from "./format.js";
import { companyInitial, jobTags, postedAgo } from "./jobcard.js";

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

// The toast's message when the caller has no notice of its own: the verdict set, or the one
// taken back when the button sent "new".
export function verdictMessage(before, after) {
  if (USER_STATUSES.has(after)) return `toast_${after}`;
  return USER_STATUSES.has(before) ? `toast_un${before}` : "toast_updated";
}

// Sends a verdict and shows its toast, whose Undo sends the earlier status back. onChange
// (changed, { undo }) hears both and may answer the toast's message (a notice). Throws when the
// verdict's request fails; a failed Undo says so in a toast of its own.
export async function sendVerdict(match, status, onChange) {
  const before = match.status;
  const updated = await api.patch(`/matches/${match.id}`, { status });
  const notice = onChange ? onChange(updated) || null : null;
  const back = undoStatus(before);
  showToast({
    message: notice || t(verdictMessage(before, updated.status)),
    action: {
      label: t("undo"),
      run: async () => {
        try {
          const restored = await api.patch(`/matches/${updated.id}`, { status: back });
          if (onChange) onChange(restored, { undo: true });
        } catch (e) {
          showToast({ message: t("request_failed"), kind: "error" });
        }
      },
    },
  });
  return updated;
}

// Returns { update(match, {focus}), close(restoreFocus = true), id, match }.
export function openDetail(host, match, opts = {}) {
  const opener = document.activeElement;
  let current = match;
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

  // Each change, the verdict's and its Undo's. Undo may come after the panel closed or moved
  // to another job, so the panel only follows a change to the job it still shows.
  function onChange(changed, { undo = false } = {}) {
    if (!closed && current.id === changed.id) {
      current = changed;
      if (undo) draw("none");
    }
    return opts.onVerdict ? opts.onVerdict(changed) : null;
  }

  async function verdict(status, action) {
    if (pending || current.status === status) return;
    pending = true;
    error = null;
    draw(action);
    try {
      await sendVerdict(current, status, onChange);
    } catch (e) {
      if (closed) return;
      error = t("request_failed");
    }
    pending = false;
    if (!closed) draw(action);
  }

  // An icon-only verdict toggle: pressed when the verdict is on, a click takes it back.
  function toggle(action, verdictName, on, iconOn, iconOff, labelOn, labelOff) {
    const label = t(on ? labelOn : labelOff);
    return h(
      "button",
      {
        class: `js-btn js-btn--ghost js-icon-btn dt-toggle dt-toggle--${action}`,
        type: "button",
        disabled: pending,
        "aria-pressed": on ? "true" : "false",
        "aria-label": label,
        title: label,
        "data-action": action,
        onclick: () => verdict(nextStatus(current.status, verdictName), action),
      },
      icon(on ? iconOn : iconOff, 18),
    );
  }

  // Ten segments, lit up to the score.
  function meter(score) {
    const lit = Math.round(Math.max(0, Math.min(100, score)) / 10);
    return h(
      "div",
      { class: "dt-meter", role: "img", "aria-label": t("fit_meter", { n: Math.round(score) }) },
      Array.from({ length: 10 }, (_, i) => h("span", { class: `dt-meter__seg${i < lit ? " is-on" : ""}` })),
    );
  }

  function draw(focusAction) {
    const job = current.job;
    const score = scoreLabel(current.score);
    const level = scoreLevel(current.score);
    const ago = postedAgo(job);
    const url = safeUrl(job.url);
    const status = current.status;
    // A job with no score has no match to give a verdict on: the panel only shows it.
    const verdicts = current.id !== null && current.id !== undefined;
    const title = h("h1", { class: "text-h1 dt-title", tabindex: "-1" }, job.title);
    const where = [job.location, ago].filter(Boolean).join(" · ");
    mount(
      host,
      h(
        "div",
        { class: "dt-body" },
        h(
          "div",
          { class: "dt-head" },
          h("span", { class: "text-meta dt-eyebrow" }, t("job_detail")),
          h(
            "div",
            { class: "dt-head__actions" },
            verdicts ? toggle("save", "saved", status === "saved", "bookmark-check", "bookmark", "saved", "save") : null,
            h("button", { class: "js-btn js-btn--ghost js-icon-btn dt-close", type: "button", "aria-label": t("close"), title: t("close"), onclick: () => close() }, icon("x", 18)),
          ),
        ),
        job.company || where
          ? h(
              "div",
              { class: "dt-company" },
              h("span", { class: "js-card__logo dt-logo", "aria-hidden": "true" }, companyInitial(job)),
              h(
                "div",
                { class: "dt-company__text" },
                job.company ? h("p", { class: "text-label dt-company__name" }, job.company) : null,
                where ? h("p", { class: "text-body-sm dt-company__where" }, where) : null,
              ),
            )
          : null,
        title,
        jobTags(job),
        score
          ? h(
              "section",
              { class: "dt-score" },
              h(
                "div",
                { class: "dt-score__row" },
                h("span", { class: "text-body-sm dt-score__label" }, t("fit_score")),
                h("span", { class: "js-tag js-tag--match dt-score__num", "data-level": level }, score),
              ),
              meter(current.score),
              current.reasoning ? h("p", { class: "text-body-sm dt-reasoning" }, current.reasoning) : null,
            )
          : null,
        h(
          "div",
          { class: "dt-lists" },
          section(t("matches_heading"), current.matched_skills, "check"),
          section(t("missing"), current.missing_skills, "minus"),
        ),
        section(t("watch_out"), current.red_flags, "alert-triangle"),
      ),
      h(
        "div",
        { class: "dt-foot" },
        error ? h("p", { class: "text-body-sm dt-error", role: "alert" }, error) : null,
        h(
          "div",
          { class: "dt-actions" },
          url
            ? h(
                "a",
                { class: "js-btn js-btn--primary dt-open", href: url, target: "_blank", rel: "noopener noreferrer", "data-action": "open" },
                job.source ? t("apply_on", { source: sourceName(job.source) }) : t("open_posting"),
                icon("arrow-up-right", 16),
              )
            : null,
          verdicts ? toggle("applied", "applied", status === "applied", "check-circle", "check-circle", "applied", "mark_applied") : null,
          verdicts ? toggle("dismiss", "dismissed", status === "dismissed", "eye-off", "eye-off", "dismissed", "dismiss") : null,
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
