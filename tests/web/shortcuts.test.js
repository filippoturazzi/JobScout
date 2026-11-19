import { test } from "node:test";
import assert from "node:assert/strict";

const { shortcutFor } = await import("../../src/jobscout/web/js/shortcuts.js");

const key = (k, mods = {}) => ({ key: k, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...mods });

test("Ctrl or Cmd K opens the palette, B folds the sidebar, Shift O starts a new search", () => {
  assert.equal(shortcutFor(key("k", { ctrlKey: true })), "palette");
  assert.equal(shortcutFor(key("K", { metaKey: true })), "palette");
  assert.equal(shortcutFor(key("b", { ctrlKey: true })), "sidebar");
  assert.equal(shortcutFor(key("O", { ctrlKey: true, shiftKey: true })), "new");
});

test("anything else is no shortcut", () => {
  assert.equal(shortcutFor(key("k")), null);
  assert.equal(shortcutFor(key("o", { ctrlKey: true })), null);
  assert.equal(shortcutFor(key("k", { ctrlKey: true, altKey: true })), null);
  assert.equal(shortcutFor(key("b", { ctrlKey: true, shiftKey: true })), null);
});
