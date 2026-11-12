import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { nextStatus, undoStatus, openDetail } = await import("../../src/jobscout/web/js/detail.js");
const { asMatch } = await import("../../src/jobscout/web/js/results.js");
const { t } = await import("../../src/jobscout/web/js/i18n.js");

const byClass = (root, name) => findElement(root, (el) => (el.getAttribute("class") || "").split(" ").includes(name));
const byAction = (root, action) => findElement(root, (el) => el.getAttribute("data-action") === action);
const job = { id: 41, source: "linkedin", title: "AI Engineer", company: "Acme", location: "Recife", url: "https://example.com/job/41", remote: true, posted_at: null, first_seen_at: "2026-11-10T10:00:00" };
const unscoredItem = { job, similarity: 0.42, match_id: null };

test("a verdict button sets its verdict, and takes it back when it is already on", () => {
  assert.equal(nextStatus("new", "saved"), "saved");
  assert.equal(nextStatus("applied", "saved"), "saved");
  assert.equal(nextStatus("saved", "saved"), "new");
  assert.equal(nextStatus("applied", "applied"), "new");
  assert.equal(nextStatus("dismissed", "dismissed"), "new");
});

test("undo restores the user's earlier verdict, or no verdict at all", () => {
  assert.equal(undoStatus("saved"), "saved");
  assert.equal(undoStatus("applied"), "applied");
  assert.equal(undoStatus("new"), "new");
  assert.equal(undoStatus("stale"), "new");
});

test("an unscored job opens with its link and no score or verdicts", () => {
  const host = fakeDocument.createElement("aside");
  openDetail(host, asMatch(unscoredItem));
  assert.ok(byAction(host, "open"));
  assert.equal(byClass(host, "js-tag--match"), null);
  for (const action of ["save", "applied", "dismiss"]) assert.equal(byAction(host, action), null);
});

test("an unscored job the ranking scores meanwhile shows its score", () => {
  const host = fakeDocument.createElement("aside");
  const panel = openDetail(host, asMatch(unscoredItem));
  panel.update({ ...asMatch(unscoredItem), id: 9, score: 81, reasoning: "Fits.", unscored: false }, { focus: false });
  assert.ok(byClass(host, "js-tag--match"));
  assert.ok(byAction(host, "save"));
});

test("an unscored job's panel does not speak of a fit score", () => {
  const host = fakeDocument.createElement("aside");
  openDetail(host, asMatch(unscoredItem));
  assert.ok(!host.textContent.includes(t("fit_score")));
});
