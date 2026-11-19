import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { convBar, cleanTitle } = await import("../../src/jobscout/web/js/convbar.js");

const byClass = (root, name) => findElement(root, (el) => (el.getAttribute("class") || "").split(" ").includes(name));
const key = (el, k) => {
  let stopped = false;
  el.listeners.keydown.forEach((fn) => fn({ key: k, preventDefault() {}, stopPropagation() { stopped = true; } }));
  return stopped;
};
const noop = () => {};
const bar = (calls = []) =>
  convBar({ id: 4, title: "Junior AI Engineer" }, 7, {
    onRename: (text) => { calls.push(text); return Promise.resolve(); },
    onExport: noop,
    onDelete: noop,
  });

test("cleanTitle collapses spaces and refuses a blank or unchanged title", () => {
  assert.equal(cleanTitle("  Data   engineer ", "Old"), "Data engineer");
  assert.equal(cleanTitle("   ", "Old"), null);
  assert.equal(cleanTitle(" Old ", "Old"), null);
});

test("the bar shows the title, the job count and a labelled actions menu button", () => {
  const b = bar();
  assert.equal(byClass(b.el, "conv-bar__title").textContent, "Junior AI Engineer");
  assert.equal(byClass(b.el, "conv-bar__count").getAttribute("data-count"), "7");
  const more = byClass(b.el, "conv-bar__more");
  assert.equal(more.getAttribute("aria-haspopup"), "menu");
  assert.ok(more.getAttribute("aria-label"));
});

test("Rename puts the title in a field; Enter saves the cleaned text", async () => {
  const calls = [];
  const b = bar(calls);
  b.startRename();
  const input = byClass(b.el, "conv-bar__input");
  assert.equal(input.value, "Junior AI Engineer");
  assert.equal(fakeDocument.activeElement, input);
  input.value = "  Senior   AI Engineer ";
  key(input, "Enter");
  await Promise.resolve();
  assert.deepEqual(calls, ["Senior AI Engineer"]);
});

test("Escape leaves the title as it was, without saving or reaching the page", () => {
  const calls = [];
  const b = bar(calls);
  b.startRename();
  const input = byClass(b.el, "conv-bar__input");
  input.value = "Something else";
  assert.equal(key(input, "Escape"), true);
  assert.deepEqual(calls, []);
  assert.equal(byClass(b.el, "conv-bar__input"), null);
  assert.equal(byClass(b.el, "conv-bar__title").textContent, "Junior AI Engineer");
});

test("an unchanged title is not sent", () => {
  const calls = [];
  const b = bar(calls);
  b.startRename();
  key(byClass(b.el, "conv-bar__input"), "Enter");
  assert.deepEqual(calls, []);
  assert.ok(byClass(b.el, "conv-bar__title"));
});

test("update redraws the title and the count", () => {
  const b = bar();
  b.update({ id: 4, title: "Renamed" }, 12);
  assert.equal(byClass(b.el, "conv-bar__title").textContent, "Renamed");
  assert.equal(byClass(b.el, "conv-bar__count").getAttribute("data-count"), "12");
});

test("update leaves a rename in progress alone", () => {
  const b = bar();
  b.startRename();
  b.update({ id: 4, title: "Junior AI Engineer" }, 9);
  assert.ok(byClass(b.el, "conv-bar__input"));
});
