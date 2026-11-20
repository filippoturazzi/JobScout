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

test("while a search runs, an empty composer's button is Stop, and it stops, once", async () => {
  const { fakeDocument, findElement } = await import("./fake-dom.js");
  globalThis.document = fakeDocument;
  const { composer } = await import("../../src/jobscout/web/js/composer.js");
  let stops = 0;
  const box = composer({ submitLabel: "Send", stopLabel: "Stop", running: true, onStop: () => stops++ });
  const button = findElement(box.el, (el) => el.tagName === "BUTTON");
  assert.equal(button.getAttribute("type"), "button");
  assert.equal(button.getAttribute("title"), "Stop");
  assert.ok(button.getAttribute("class").split(" ").includes("js-send--stop"));
  button.listeners.click.forEach((fn) => fn({ preventDefault() {} }));
  assert.equal(stops, 1);
});

test("a stop already asked for leaves the Stop button disabled", async () => {
  const { fakeDocument, findElement } = await import("./fake-dom.js");
  globalThis.document = fakeDocument;
  const { composer } = await import("../../src/jobscout/web/js/composer.js");
  const box = composer({ stopLabel: "Stop", running: true, stopping: true, onStop() {} });
  assert.notEqual(findElement(box.el, (el) => el.tagName === "BUTTON").getAttribute("disabled"), null);
});

test("while running, typing turns Stop into Send", async () => {
  const { fakeDocument, findElement } = await import("./fake-dom.js");
  globalThis.document = fakeDocument;
  const { composer } = await import("../../src/jobscout/web/js/composer.js");
  const sent = [];
  let stops = 0;
  const c = composer({ running: true, onSubmit: (text) => sent.push(text), onStop: () => stops++ });
  const field = findElement(c.el, (el) => el.tagName === "TEXTAREA");
  const stop = findElement(c.el, (el) => (el.getAttribute("class") || "").includes("js-send--stop"));
  const send = findElement(c.el, (el) => el.getAttribute("type") === "submit");
  assert.equal(field.getAttribute("disabled"), null);
  assert.equal(stop.hidden, false);
  assert.equal(send.hidden, true);
  field.value = "only remote";
  field.listeners.input[0]();
  assert.equal(stop.hidden, true);
  assert.equal(send.hidden, false);
  c.el.listeners.submit[0]({ preventDefault() {} });
  assert.deepEqual(sent, ["only remote"]);
  field.value = "";
  field.listeners.input[0]();
  assert.equal(stop.hidden, false);
  stop.listeners.click[0]();
  assert.equal(stops, 1);
});
