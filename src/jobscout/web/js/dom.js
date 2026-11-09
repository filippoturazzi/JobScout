// Tiny element builder. Children given as strings or numbers become text nodes,
// so data can never turn into markup.

function collect(children, out) {
  for (const child of children) {
    if (child === null || child === undefined || child === false || child === true) continue;
    if (Array.isArray(child)) collect(child, out);
    else if (typeof child === "object") out.push(child);
    else out.push(document.createTextNode(String(child)));
  }
  return out;
}

// href is set as given: posting links must go through format.js safeUrl first (detail.js does).
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    // Never let a string become an inline handler, an embedded document or inline CSS.
    if (name.startsWith("on")) {
      if (typeof value !== "function") throw new TypeError(`h(): ${name} must be a function`);
      el.addEventListener(name.slice(2).toLowerCase(), value);
    } else if (name === "srcdoc" || (name === "style" && typeof value === "string")) {
      throw new TypeError(`h(): ${name} is not allowed`);
    } else if (value === true) {
      el.setAttribute(name, "");
    } else {
      el.setAttribute(name, String(value));
    }
  }
  collect(children, []).forEach((node) => el.appendChild(node));
  return el;
}

export function mount(parent, ...children) {
  parent.replaceChildren(...collect(children, []));
}
