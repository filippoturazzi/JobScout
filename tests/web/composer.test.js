import { test } from "node:test";
import assert from "node:assert/strict";

const { shouldSubmit } = await import("../../src/jobscout/web/js/composer.js");

test("an empty or whitespace text never submits", () => {
  assert.equal(shouldSubmit("", {}), false);
  assert.equal(shouldSubmit("  \n", {}), false);
});

test("a disabled composer never submits", () => {
  assert.equal(shouldSubmit("a job", { disabled: true }), false);
});

test("text submits", () => {
  assert.equal(shouldSubmit("a job", {}), true);
  assert.equal(shouldSubmit("  a job \n", { disabled: false }), true);
});

test("a rebuilt composer takes the focus back, caret at the end, only if the old one had it", async () => {
  const { fakeDocument } = await import("./fake-dom.js");
  globalThis.document = fakeDocument;
  const { composer } = await import("../../src/jobscout/web/js/composer.js");
  const old = composer({});
  assert.equal(old.hasFocus(), false);
  old.focus();
  assert.equal(old.hasFocus(), true);
  const fresh = composer({});
  fresh.setText("remote only");
  fresh.focus({ end: true });
  assert.equal(fresh.hasFocus(), true);
  assert.equal(old.hasFocus(), false);
  assert.deepEqual(fakeDocument.activeElement.selection, [11, 11]);
});

test("a composer asked for the highlight carries it; others do not", async () => {
  const { fakeDocument } = await import("./fake-dom.js");
  globalThis.document = fakeDocument;
  const { composer } = await import("../../src/jobscout/web/js/composer.js");
  const classes = (box) => box.el.getAttribute("class").split(" ");
  assert.ok(classes(composer({ multiline: true, highlight: true })).includes("js-highlight"));
  assert.ok(!classes(composer({})).includes("js-highlight"));
});
