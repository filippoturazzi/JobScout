import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { h, mount } = await import("../../src/jobscout/web/js/dom.js");

test("string children become text, not markup", () => {
  const p = h("p", {}, "<img onerror=x>");
  assert.equal(p.childNodes[0].nodeType, 3);
  assert.equal(p.textContent, "<img onerror=x>");
  assert.equal(p.childNodes.length, 1);
});

test("numbers become text too", () => {
  assert.equal(h("span", {}, 3).textContent, "3");
});

test("null and false children are skipped; arrays flatten", () => {
  const ul = h("ul", {}, null, false, [h("li", {}, "a"), [h("li", {}, "b")]], undefined);
  assert.equal(ul.childNodes.length, 2);
  assert.equal(ul.textContent, "ab");
});

test("on* attributes attach listeners", () => {
  let clicked = 0;
  const b = h("button", { onclick: () => clicked++ }, "go");
  b.listeners.click[0]();
  assert.equal(clicked, 1);
  assert.equal(b.getAttribute("onclick"), null);
});

test("class, aria, data and boolean attributes", () => {
  const b = h("button", { class: "js-btn", "aria-label": "x", "data-id": 4, disabled: true, hidden: false });
  assert.equal(b.getAttribute("class"), "js-btn");
  assert.equal(b.getAttribute("aria-label"), "x");
  assert.equal(b.getAttribute("data-id"), "4");
  assert.equal(b.getAttribute("disabled"), "");
  assert.equal(b.getAttribute("hidden"), null);
});

test("a string on* attribute throws and sets nothing", () => {
  const el = document.createElement("a");
  assert.throws(() => h("a", { onclick: "alert(1)" }), TypeError);
  assert.equal(el.getAttribute("onclick"), null);
});

test("srcdoc and string style are refused", () => {
  assert.throws(() => h("iframe", { srcdoc: "<p>x</p>" }), TypeError);
  assert.throws(() => h("p", { style: "color:red" }), TypeError);
});

test("mount replaces the children", () => {
  const root = h("div", {}, "old");
  mount(root, "new", null, h("b", {}, "x"));
  assert.equal(root.textContent, "newx");
  assert.equal(root.childNodes.length, 2);
});
