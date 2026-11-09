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
  setSelectionRange(start, end) {
    this.selection = [start, end];
  }
  get textContent() {
    return this.childNodes.map((n) => n.textContent).join("");
  }
}

export const fakeDocument = {
  activeElement: null,
  createElement: (tag) => new FakeElement(tag),
  createTextNode: (data) => new FakeText(data),
};
