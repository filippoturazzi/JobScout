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

test("a verdict's toast names what it set, or what it took back", async () => {
  const { verdictMessage } = await import("../../src/jobscout/web/js/detail.js");
  assert.equal(verdictMessage("new", "saved"), "toast_saved");
  assert.equal(verdictMessage("saved", "applied"), "toast_applied");
  assert.equal(verdictMessage("new", "dismissed"), "toast_dismissed");
  assert.equal(verdictMessage("saved", "new"), "toast_unsaved");
  assert.equal(verdictMessage("dismissed", "new"), "toast_undismissed");
  assert.equal(verdictMessage("stale", "new"), "toast_updated");
});

// A stand-in for `window`: the panel listens for "focus" on it, the user coming back.
function fakeWindow() {
  const listeners = new Set();
  return {
    addEventListener: (type, fn) => type === "focus" && listeners.add(fn),
    removeEventListener: (type, fn) => listeners.delete(fn),
    comeBack: () => [...listeners].forEach((fn) => fn({})),
    get count() {
      return listeners.size;
    },
  };
}
const scored = (extra = {}) => ({ id: 9, score: 81, status: "new", reasoning: "Fits.", matched_skills: [], missing_skills: [], red_flags: [], job, ...extra });
const clickApply = (host) => byAction(host, "open").listeners.click.forEach((fn) => fn({}));

test("coming back after Apply asks whether you applied", () => {
  const win = fakeWindow();
  const host = fakeDocument.createElement("aside");
  openDetail(host, scored(), { focusTarget: win });
  assert.equal(byClass(host, "dt-ask"), null);
  clickApply(host);
  win.comeBack();
  assert.ok(byClass(host, "dt-ask"));
  assert.ok(byAction(host, "ask-yes") && byAction(host, "ask-no"));
});

test("coming back without pressing Apply asks nothing", () => {
  const win = fakeWindow();
  const host = fakeDocument.createElement("aside");
  openDetail(host, scored(), { focusTarget: win });
  win.comeBack();
  assert.equal(byClass(host, "dt-ask"), null);
});

test("Not yet puts the question away, and it is asked once per Apply", () => {
  const win = fakeWindow();
  const host = fakeDocument.createElement("aside");
  openDetail(host, scored(), { focusTarget: win });
  clickApply(host);
  win.comeBack();
  byAction(host, "ask-no").listeners.click.forEach((fn) => fn({}));
  assert.equal(byClass(host, "dt-ask"), null);
  win.comeBack();
  assert.equal(byClass(host, "dt-ask"), null);
});

test("a job already applied for, or with no score, is never asked about", () => {
  for (const match of [scored({ status: "applied" }), asMatch(unscoredItem)]) {
    const win = fakeWindow();
    const host = fakeDocument.createElement("aside");
    openDetail(host, match, { focusTarget: win });
    clickApply(host);
    win.comeBack();
    assert.equal(byClass(host, "dt-ask"), null);
  }
});

test("the question belongs to the job: moving to another one drops it", () => {
  const win = fakeWindow();
  const host = fakeDocument.createElement("aside");
  const panel = openDetail(host, scored(), { focusTarget: win });
  clickApply(host);
  panel.update(scored({ id: 10 }));
  win.comeBack();
  assert.equal(byClass(host, "dt-ask"), null);
});

test("a closed panel stops listening for the user coming back", () => {
  const win = fakeWindow();
  const host = fakeDocument.createElement("aside");
  const panel = openDetail(host, scored(), { focusTarget: win });
  assert.equal(win.count, 1);
  panel.close(false);
  assert.equal(win.count, 0);
});
