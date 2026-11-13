// Toasts: one at a time, at the bottom centre of the main area, gone after 6 s (held while the
// pointer or the keyboard is on it). A toast may carry one action, such as Undo.
import { h, mount } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";

export const TOAST_MS = 6000;

let host = null;
let timer = null;
let current = null; // { onExpire }

// host: a persistent element the shell keeps on the page (role="status", so it is announced).
export function initToasts(el) {
  host = el;
}

function stopTimer() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function startTimer(ms) {
  stopTimer();
  timer = setTimeout(() => hideToast(), ms);
}

// Removes the toast. The one it replaces or that expires runs its onExpire (a pending delete
// goes through then); an action taken on it does not.
export function hideToast({ expire = true } = {}) {
  stopTimer();
  const was = current;
  current = null;
  if (host) mount(host);
  if (was && expire && was.onExpire) was.onExpire();
}

// opts: { message, kind: "success" | "error", action: { label, run }, onExpire }
export function showToast({ message, kind = "success", action = null, onExpire = null }) {
  if (!host) return;
  hideToast();
  current = { onExpire };
  const actionButton = action
    ? h(
        "button",
        {
          class: "js-btn js-btn--ghost toast__action text-label",
          type: "button",
          onclick: () => {
            hideToast({ expire: false });
            action.run();
          },
        },
        action.label,
      )
    : null;
  const el = h(
    "div",
    {
      class: `toast toast--${kind}`,
      onmouseenter: stopTimer,
      onmouseleave: () => startTimer(TOAST_MS / 2),
      onfocusin: stopTimer,
      onfocusout: () => startTimer(TOAST_MS / 2),
    },
    h("span", { class: "toast__icon" }, icon(kind === "error" ? "alert-triangle" : "check-circle", 16)),
    h("p", { class: "text-body-sm toast__text" }, message),
    actionButton,
    h(
      "button",
      { class: "js-btn js-btn--ghost js-icon-btn js-icon-btn--sm toast__close", type: "button", "aria-label": t("close"), title: t("close"), onclick: () => hideToast() },
      icon("x", 14),
    ),
  );
  mount(host, el);
  startTimer(TOAST_MS);
}
