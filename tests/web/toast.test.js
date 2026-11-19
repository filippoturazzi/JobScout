import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { initToasts, showToast, hideToast } = await import("../../src/jobscout/web/js/toast.js");

const host = fakeDocument.createElement("div");
initToasts(host);
const byClass = (name) => findElement(host, (el) => (el.getAttribute("class") || "").split(" ").includes(name));

test("a toast shows its message and replaces the one before, which expires", () => {
  let expired = 0;
  showToast({ message: "First", onExpire: () => expired++ });
  showToast({ message: "Second" });
  assert.equal(host.childNodes.length, 1);
  assert.equal(byClass("toast__text").textContent, "Second");
  assert.equal(expired, 1);
  hideToast();
});

test("its action runs once and does not count as expiring", () => {
  let undone = 0;
  let expired = 0;
  showToast({ message: "Saved", action: { label: "Undo", run: () => undone++ }, onExpire: () => expired++ });
  byClass("toast__action").listeners.click[0]();
  assert.equal(undone, 1);
  assert.equal(expired, 0);
  assert.equal(host.childNodes.length, 0);
});

test("closing a toast expires it", () => {
  let expired = 0;
  showToast({ message: "Deleted", onExpire: () => expired++ });
  byClass("toast__close").listeners.click[0]();
  assert.equal(expired, 1);
  assert.equal(host.childNodes.length, 0);
});
