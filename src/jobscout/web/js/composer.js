// The pinned composer used by every view: a textarea with a submit button.
// Enter submits, Shift+Enter adds a line; empty text never submits.
import { h } from "./dom.js";
import { icon } from "./icons.js";

export function shouldSubmit(text, { disabled } = {}) {
  return !disabled && String(text).trim().length > 0;
}

// running: a search is in flight. The field stays open, so a refinement can be typed: the
// button is Stop (onStop) while the field is empty and Send once it has text.
// stopping: the Stop was sent and the Stop button waits, disabled, for the run to end.
export function composer({ placeholder = "", disabled = false, locked: lockedIn = false, multiline = false, submitLabel = "", submitIcon = null, primary = true, highlight = false, onSubmit, running = false, stopping = false, stopLabel = "", onStop } = {}) {
  const locked = lockedIn;
  let isDisabled = disabled;
  const field = h("textarea", {
    class: "composer__field",
    rows: multiline ? 3 : 1,
    placeholder,
    "aria-label": placeholder,
    disabled: locked,
  });
  // The submit is the round, icon-only Send; its words stay for screen readers and the tooltip.
  const stop = running
    ? h(
        "button",
        {
          class: "js-btn js-send js-send--stop",
          type: "button",
          title: stopLabel,
          disabled: stopping,
          onclick: () => {
            if (!stopping && onStop) onStop();
          },
        },
        icon("square", 14),
        h("span", { class: "sr-only" }, stopLabel),
      )
    : null;
  const label = h("span", { class: "sr-only" }, submitLabel);
  const button = h(
    "button",
    {
      class: `js-btn js-send${primary ? "" : " js-send--quiet"}`,
      type: "submit",
      title: submitLabel,
      disabled: isDisabled || locked,
    },
    icon(submitIcon || "arrow-up", 18),
    label,
  );
  // While running, only one of Stop and Send shows: Send once there is text to send.
  function syncRunning() {
    if (!stop) return;
    const typed = String(field.value || "").trim().length > 0;
    stop.hidden = typed;
    button.hidden = !typed;
  }
  field.addEventListener("input", syncRunning);
  syncRunning();
  const el = h(
    "form",
    { class: `js-pref composer${multiline ? " composer--multiline" : ""}${highlight ? " js-highlight" : ""}`, novalidate: true },
    field,
    h("div", { class: "js-pref__foot composer__foot" }, locked ? icon("lock") : h("span", {}), stop, button),
  );

  function submit() {
    if (!shouldSubmit(field.value, { disabled: isDisabled || locked })) return;
    if (onSubmit) onSubmit(field.value.trim());
  }
  el.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  });

  return {
    el,
    // end: put the caret after the text (a redraw rebuilt the field under the user's typing).
    focus: ({ end = false } = {}) => {
      field.focus();
      if (end && typeof field.setSelectionRange === "function") {
        const n = String(field.value || "").length;
        field.setSelectionRange(n, n);
      }
    },
    hasFocus: () => typeof document !== "undefined" && document.activeElement === field,
    getText: () => field.value,
    setText: (s) => {
      field.value = s;
      syncRunning();
    },
    setPlaceholder: (s) => {
      field.setAttribute("placeholder", s);
      field.setAttribute("aria-label", s);
    },
    setDisabled: (b) => {
      isDisabled = b;
      if (b || locked) button.setAttribute("disabled", "");
      else button.removeAttribute("disabled");
    },
    setSubmitLabel: (s) => {
      label.textContent = s;
      button.setAttribute("title", s);
    },
  };
}
