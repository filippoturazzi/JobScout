// The summary's edit modal: one question in a <dialog>, saved with Save, never in the transcript.
import { singleAnswer } from "./conversation.js";

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

// The selection the modal opens on: the stored answer, or the summary's role.
export function initialSelection(q, answer, summary) {
  const sel = { option: null, picked: [], any: false, text: "" };
  const kind = editKind(q);
  if (kind === "text") {
    sel.text = ((summary && summary.terms) || []).join(", ");
    return sel;
  }
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
