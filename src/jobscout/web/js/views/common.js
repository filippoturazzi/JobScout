// Small helpers shared by the views.
import { h } from "../dom.js";

// Fixed copy may mention configuration names; show them as code, never as markup.
export function withCode(text, names) {
  const escaped = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`));
  return parts.map((part) => (names.includes(part) ? h("span", { class: "text-meta" }, part) : part));
}
