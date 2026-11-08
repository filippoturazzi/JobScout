// The pinned composer used by every view: a textarea with a submit button.
// Enter submits, Shift+Enter adds a line; empty text never submits.
import { h } from "./dom.js";
import { icon } from "./icons.js";

export function shouldSubmit(text, { disabled } = {}) {
  return !disabled && String(text).trim().length > 0;
}

export function composer({ placeholder = "", disabled = false, locked = false, multiline = false, submitLabel = "", primary = true, onSubmit } = {}) {
  let isDisabled = disabled;
  const field = h("textarea", {
    class: "composer__field",
    rows: multiline ? 3 : 1,
    placeholder,
    "aria-label": placeholder,
    disabled: locked,
  });
  const button = h(
    "button",
    { class: `js-btn ${primary ? "js-btn--primary" : "js-btn--secondary"}`, type: "submit", disabled: isDisabled || locked },
    submitLabel,
  );
  const el = h(
    "form",
    { class: `js-pref composer${multiline ? " composer--multiline" : ""}`, novalidate: true },
    field,
    h("div", { class: "js-pref__foot composer__foot" }, locked ? icon("lock") : h("span", {}), button),
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
    focus: () => field.focus(),
    getText: () => field.value,
    setText: (s) => {
      field.value = s;
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
      button.textContent = s;
    },
  };
}
