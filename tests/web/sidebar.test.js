import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { renderSidebar } = await import("../../src/jobscout/web/js/sidebar.js");

const newSearch = (route) => {
  const root = fakeDocument.createElement("div");
  renderSidebar(root, { searches: [] }, route, () => {});
  return findElement(root, (el) => (el.getAttribute("class") || "").split(" ").includes("sb-new"));
};

test("New search is highlighted on every screen, and the current page on Home only", () => {
  const home = newSearch({ name: "home" });
  assert.ok(home.getAttribute("class").split(" ").includes("js-highlight"));
  assert.equal(home.getAttribute("aria-current"), "page");
  const elsewhere = newSearch({ name: "search", id: 3 });
  assert.ok(elsewhere.getAttribute("class").split(" ").includes("js-highlight"));
  assert.equal(elsewhere.getAttribute("aria-current"), null);
});
