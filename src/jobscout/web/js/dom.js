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

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith("on") && typeof value === "function") {
      el.addEventListener(name.slice(2).toLowerCase(), value);
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
