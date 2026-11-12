import { test } from "node:test";
import assert from "node:assert/strict";

const { resultsLayout, PER_PAGE, HIGHLIGHTED } = await import("../../src/jobscout/web/js/resultslayout.js");

const scored = (n) => Array.from({ length: n }, (_, i) => ({ id: i + 1, score: 90 - i, job: { id: i + 1 } }));
const unscored = (n) => Array.from({ length: n }, (_, i) => ({ job: { id: 1000 + i }, similarity: null, match_id: null }));
const kinds = (items) => items.map((it) => it.kind);

test("resultsLayout: constants", () => {
  assert.equal(PER_PAGE, 9);
  assert.equal(HIGHLIGHTED, 3);
});

test("resultsLayout: 15 scored spread over two pages after the highlighted three", () => {
  const first = resultsLayout(scored(15), [], 1);
  assert.equal(first.highlighted.length, 3);
  assert.deepEqual(first.highlighted.map((m) => m.id), [1, 2, 3]);
  assert.deepEqual(kinds(first.items), Array(9).fill("match"));
  assert.equal(first.items[0].match.id, 4);
  assert.equal(first.pages, 2);
  const second = resultsLayout(scored(15), [], 2);
  assert.equal(second.highlighted.length, 0);
  assert.deepEqual(second.items.map((it) => it.match.id), [13, 14, 15]);
});

test("resultsLayout: fewer than three scored are all highlighted", () => {
  const v = resultsLayout(scored(2), [], 1);
  assert.equal(v.highlighted.length, 2);
  assert.deepEqual(v.items, []);
  assert.equal(v.pages, 1);
});

test("resultsLayout: exactly three scored is the highlighted row alone", () => {
  const v = resultsLayout(scored(3), [], 1);
  assert.equal(v.highlighted.length, 3);
  assert.deepEqual(v.items, []);
  assert.equal(v.pages, 1);
});

test("resultsLayout: nothing scored starts at the divider", () => {
  const v = resultsLayout([], unscored(4), 1);
  assert.equal(v.highlighted.length, 0);
  assert.deepEqual(kinds(v.items), ["divider", "unscored", "unscored", "unscored", "unscored"]);
});

test("resultsLayout: the divider sits where the scored group ends", () => {
  const v = resultsLayout(scored(5), unscored(65), 1);
  assert.deepEqual(kinds(v.items), ["match", "match", "divider", ...Array(7).fill("unscored")]);
  assert.equal(v.pages, 8);
  const later = resultsLayout(scored(5), unscored(65), 2);
  assert.deepEqual(kinds(later.items), Array(9).fill("unscored"));
});

test("resultsLayout: a scored group ending on a page boundary opens the next page with the divider", () => {
  const first = resultsLayout(scored(12), unscored(5), 1);
  assert.deepEqual(kinds(first.items), Array(9).fill("match"));
  const second = resultsLayout(scored(12), unscored(5), 2);
  assert.deepEqual(kinds(second.items), ["divider", ...Array(5).fill("unscored")]);
});

test("resultsLayout: the page is clamped to the pages there are", () => {
  assert.equal(resultsLayout(scored(24), [], 9).page, 3);
  assert.equal(resultsLayout(scored(24), [], 9).pages, 3);
  assert.equal(resultsLayout(scored(24), [], 0).page, 1);
  assert.equal(resultsLayout([], [], 4).page, 1);
});
