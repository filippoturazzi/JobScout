import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { runSection } = await import("../../src/jobscout/web/js/results.js");

const scored = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1, score: 90 - i, status: "new", job: { id: i + 1, title: `Job ${i + 1}`, source: "linkedin" } }));
const view = (matches) => ({ state: "results", found: matches.length, waiting: 0, matches, unscored: [], widen: false, failures: [], runError: null });

function render(page, onPage) {
  const host = fakeDocument.createElement("div");
  const ui = { selectedId: null, page, busyOther: null };
  const handlers = { onSearchAgain() {}, onRank() {}, onWiden() {}, onOpen() {}, onPage };
  runSection(view(scored(24)), { widenings: [] }, ui, handlers).forEach((n) => host.appendChild(n));
  return host;
}

test("pager buttons say which control they are, so focus can come back to it", () => {
  const calls = [];
  const host = render(2, (n, key) => calls.push([n, key]));
  const next = findElement(host, (el) => el.getAttribute("data-pager") === "next");
  const prev = findElement(host, (el) => el.getAttribute("data-pager") === "prev");
  const three = findElement(host, (el) => el.getAttribute("data-pager") === "3");
  next.listeners.click[0]();
  prev.listeners.click[0]();
  three.listeners.click[0]();
  assert.deepEqual(calls, [[3, "next"], [1, "prev"], [3, "3"]]);
});

const hasClass = (el, name) => (el.getAttribute("class") || "").split(" ").includes(name);
const cardsIn = (root) => {
  const out = [];
  const walk = (node) => node.childNodes.forEach((c) => { if (c.nodeType === 1) { if (c.tagName === "ARTICLE") out.push(c); walk(c); } });
  walk(root);
  return out;
};

test("every result card looks the same: none carries the highlight", () => {
  const host = render(1, () => {});
  const cards = cardsIn(host);
  assert.deepEqual(cards.map((c) => hasClass(c, "js-highlight")), Array(12).fill(false));
});

test("a page holding only unscored jobs renders them, past the page with the divider", () => {
  // 3 highlighted + 11 scored + 22 unscored: page 2 has the divider, pages 3 and 4 do not.
  const unscored = Array.from({ length: 22 }, (_, i) => ({ similarity: 0.5, job: { id: 100 + i, title: `Loose ${i + 1}`, source: "indeed" } }));
  const v = { ...view(scored(14)), unscored, waiting: 22 };
  const handlers = { onSearchAgain() {}, onRank() {}, onWiden() {}, onOpen() {}, onPage() {} };
  for (const [page, n] of [[3, 9], [4, 6]]) {
    const host = fakeDocument.createElement("div");
    runSection(v, { widenings: [] }, { selectedId: null, page, busyOther: null }, handlers).forEach((node) => host.appendChild(node));
    assert.equal(cardsIn(host).length, n, `page ${page}`);
    const current = findElement(host, (el) => el.getAttribute("aria-current") === "page");
    assert.equal(current.getAttribute("data-pager"), String(page));
  }
});

const textOf = (nodes) => {
  const host = fakeDocument.createElement("div");
  nodes.forEach((n) => host.appendChild(n));
  return host.textContent;
};
const noHandlers = { onSearchAgain() {}, onRank() {}, onWiden() {}, onOpen() {}, onPage() {} };

test("a stopped run's results say the user stopped it", () => {
  const v = { ...view(scored(2)), stopped: true };
  assert.ok(textOf(runSection(v, { widenings: [] }, { page: 1, busyOther: null }, noHandlers)).includes("stopped_note"));
  assert.ok(!textOf(runSection(view(scored(2)), { widenings: [] }, { page: 1, busyOther: null }, noHandlers)).includes("stopped_note"));
});

test("a run stopped before anything came in says that, not that nothing fit", () => {
  const v = { state: "nothing", stopped: true, searched: 1, fetched: 0, failures: [], runError: null };
  const text = textOf(runSection(v, { widenings: [], summary: {} }, { busyOther: null }, noHandlers));
  assert.ok(text.includes("stopped_nothing"));
  assert.ok(!text.includes("nothing_found"));
});

test("while a stop is on its way the running headline says it is stopping", () => {
  const v = { state: "running", searchedSources: true, sources: [], progress: { sources: 0, scored: 0, toScore: 0 }, matches: [], failures: [] };
  const text = textOf(runSection(v, { widenings: [] }, { stopping: true, busyOther: null }, noHandlers));
  assert.ok(text.includes("stopping"));
});
