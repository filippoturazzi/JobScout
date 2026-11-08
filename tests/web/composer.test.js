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
