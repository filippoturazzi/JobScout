import { test } from "node:test";
import assert from "node:assert/strict";

const { readTheme, resolveTheme } = await import("../../src/jobscout/web/js/theme.js");

test("the saved choice is dark, light or system, and dark when nothing valid is saved", () => {
  assert.equal(readTheme("light"), "light");
  assert.equal(readTheme("system"), "system");
  assert.equal(readTheme("dark"), "dark");
  assert.equal(readTheme(null), "dark");
  assert.equal(readTheme("sepia"), "dark");
});

test("system follows the operating system; a fixed choice ignores it", () => {
  assert.equal(resolveTheme("system", true), "light");
  assert.equal(resolveTheme("system", false), "dark");
  assert.equal(resolveTheme("dark", true), "dark");
  assert.equal(resolveTheme("light", false), "light");
});
