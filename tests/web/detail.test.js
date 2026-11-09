import { test } from "node:test";
import assert from "node:assert/strict";
import { fakeDocument } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { nextStatus, undoStatus } = await import("../../src/jobscout/web/js/detail.js");

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
