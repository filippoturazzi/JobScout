// A minimal document, just enough for js/dom.js. Not a browser.
class FakeNode {
  constructor(nodeType) {
    this.nodeType = nodeType;
    this.childNodes = [];
  }
}

class FakeText extends FakeNode {
  constructor(data) {
    super(3);
    this.data = String(data);
  }
  get textContent() {
    return this.data;
  }
}

class FakeElement extends FakeNode {
  constructor(tag) {
    super(1);
    this.tagName = tag.toUpperCase();
    this.attributes = {};
    this.listeners = {};
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }
  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }
  appendChild(node) {
    this.childNodes.push(node);
    return node;
  }
  replaceChildren(...nodes) {
    this.childNodes = [];
    nodes.forEach((n) => this.appendChild(n));
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  focus() {
    fakeDocument.activeElement = this;
  }
  // Only `[name="value"]`, the one selector detail.js asks for.
  querySelector(selector) {
    const m = /^\[([\w-]+)="([^"]*)"\]$/.exec(selector);
    if (!m) return null;
    return findElement(this, (el) => el.getAttribute(m[1]) === m[2]);
  }
  contains(node) {
    return node === this || Boolean(findElement(this, (el) => el === node));
  }
  setSelectionRange(start, end) {
    this.selection = [start, end];
  }
  get textContent() {
    return this.childNodes.map((n) => n.textContent).join("");
  }
}

// The first element under `root` (not root itself) for which `test` holds.
export function findElement(root, test) {
  for (const child of root.childNodes) {
    if (child.nodeType !== 1) continue;
    if (test(child)) return child;
    const found = findElement(child, test);
    if (found) return found;
  }
  return null;
}

export const fakeDocument = {
  activeElement: null,
  addEventListener() {},
  removeEventListener() {},
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (data) => new FakeText(data),
};
