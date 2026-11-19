// The summary's edit modal: one question in a <dialog>, saved with Save, never in the transcript.
import { h } from "./dom.js";
import { icon } from "./icons.js";
import { t } from "./i18n.js";
import { optionLabel, questionText, singleAnswer } from "./conversation.js";

// "text" for the role, "multi" for work mode and skills, "single" for the rest.
export function editKind(q) {
  if (q.id === "role") return "text";
  return q.multi ? "multi" : "single";
}

// sel: { option, picked, any, text }. The answer Save sends, or null while Save must wait.
export function answerFor(q, sel) {
  const text = String(sel.text || "").trim();
  switch (editKind(q)) {
    case "text":
      return text.split(",").some((part) => part.trim()) ? { choice: "role", values: [text] } : null;
    case "multi":
      if (sel.any) return { choice: "any", values: [] };
      return sel.picked.length ? { choice: "pick", values: [...sel.picked] } : null;
    default:
      if (!sel.option) return null;
      if (sel.option.choice === "other") return text ? { choice: q.id === "city" ? "city" : "country", values: [text] } : null;
      return singleAnswer(sel.option);
  }
}

// What a row shows when the reading, not a click, decided it.
function fromSummary(qid, summary) {
  if (qid === "level" && summary.level) return { choice: summary.level, values: [] };
  if (qid === "work_modes" && (summary.work_modes || []).length) return { choice: "pick", values: summary.work_modes };
  if (qid === "skills" && (summary.skills || []).length) return { choice: "pick", values: summary.skills };
  return null;
}

// The selection the modal opens on: the stored answer, or the summary's role.
export function initialSelection(q, answer, summary) {
  const sel = { option: null, picked: [], any: false, text: "" };
  const kind = editKind(q);
  if (kind === "text") {
    sel.text = ((summary && summary.terms) || []).join(", ");
    return sel;
  }
  if (!answer) answer = fromSummary(q.id, summary || {});
  if (!answer) return sel;
  if (kind === "multi") {
    if (answer.choice === "any") sel.any = true;
    else if (answer.choice === "pick") sel.picked = [...(answer.values || [])];
    return sel;
  }
  const value = (answer.values || [])[0];
  const match = q.options.find((o) => o.choice === answer.choice && (o.value == null || o.value === value));
  if (match) sel.option = match;
  else if (value && (answer.choice === "city" || answer.choice === "country")) {
    sel.option = q.options.find((o) => o.choice === "other") || null;
    sel.text = value;
  }
  return sel;
}

// --- The dialog ----------------------------------------------------------------------------

let open = null;

// opts: { country, answer, summary, onSave(answer) -> Promise }. Save does not close the
// dialog: the caller closes it once the API has taken the answer, or shows its error here.
export function openEditModal(q, { country, answer, summary, onSave, onClose } = {}) {
  if (open) open.close();
  const kind = editKind(q);
  const sel = initialSelection(q, answer, summary);
  let busy = false;
  const title = questionText(q.id, country);
  const error = h("p", { class: "text-body-sm conv-error em-error", role: "alert", hidden: true });
  const save = h("button", { class: "js-btn js-btn--primary", type: "submit" }, t("save"));
  const placeholder = kind === "text" ? t("q_role") : q.id === "city" ? t("type_city") : t("type_country");
  const field = h("input", { class: "text-body em-field", type: "text", "aria-label": placeholder, placeholder });
  field.value = sel.text;
  field.addEventListener("input", () => {
    sel.text = field.value;
    sync();
  });

  const chips = [];
  for (const option of kind === "text" ? [] : q.options) {
    const el = h("button", { class: "js-btn js-btn--secondary conv-chip", type: "button", "aria-pressed": "false" }, h("span", { class: "conv-chip__check" }, icon("check", 14)), optionLabel(q.id, option, country));
    el.addEventListener("click", () => {
      if (kind === "multi") {
        const key = option.choice === "skill" ? option.value : option.choice;
        if (option.choice === "any") {
          sel.any = !sel.any;
          sel.picked = [];
        } else {
          sel.any = false;
          sel.picked = sel.picked.includes(key) ? sel.picked.filter((k) => k !== key) : [...sel.picked, key];
        }
      } else sel.option = option;
      sync();
      if (kind === "single" && option.choice === "other") field.focus();
    });
    chips.push({ el, option });
  }

  const fieldRow = h("div", { class: "em-field-row" }, field);
  function sync() {
    for (const { el, option } of chips) {
      const key = option.choice === "skill" ? option.value : option.choice;
      const on = kind === "multi" ? (option.choice === "any" ? sel.any : sel.picked.includes(key)) : sel.option === option;
      el.setAttribute("aria-pressed", String(on));
      el.classList.toggle("is-on", on);
    }
    fieldRow.hidden = !(kind === "text" || (sel.option && sel.option.choice === "other"));
    save.disabled = busy || answerFor(q, sel) === null;
  }

  const form = h(
    "form",
    { class: "em-form", method: "dialog", novalidate: true },
    h("h2", { class: "text-h2 em-title", id: "em-title" }, title),
    chips.length ? h("div", { class: "conv-chips em-chips", role: kind === "multi" ? "group" : "radiogroup", "aria-label": title }, chips.map((c) => c.el)) : null,
    fieldRow,
    error,
    h("div", { class: "em-actions" }, h("button", { class: "js-btn js-btn--ghost", type: "button", onclick: () => dialog.close() }, t("cancel")), save),
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const next = answerFor(q, sel);
    if (busy || next === null) return;
    controls.busy(true);
    try {
      await onSave(next);
    } finally {
      controls.busy(false);
    }
  });

  const dialog = h(
    "dialog",
    {
      class: "em",
      "aria-labelledby": "em-title",
      // A click on the backdrop lands on the dialog itself: treat it as Cancel.
      onclick: (e) => { if (e.target === dialog) dialog.close(); },
      onclose: () => {
        dialog.remove();
        if (open === controls) open = null;
        if (onClose) onClose();
      },
    },
    form,
  );

  const controls = {
    close: () => { if (dialog.open) dialog.close(); },
    showError(text) {
      error.textContent = text;
      error.hidden = !text;
    },
    busy(on) {
      busy = on;
      sync();
    },
  };
  open = controls;
  sync();
  document.body.appendChild(dialog);
  dialog.showModal();
  const first = !fieldRow.hidden ? field : (chips.find((c) => c.el.classList.contains("is-on")) || chips[0] || {}).el;
  if (first) first.focus();
  return controls;
}
