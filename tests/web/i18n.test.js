import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const webDir = new URL("../../src/jobscout/web/", import.meta.url);
globalThis.fetch = async (url) => {
  const path = String(url).replace(/^\/static\//, "");
  const text = await readFile(new URL(path, webDir), "utf8");
  return { ok: true, json: async () => JSON.parse(text) };
};
const { loadLocale, t, currentLocale } = await import("../../src/jobscout/web/js/i18n.js");
await loadLocale("en");

test("t fills placeholders", () => {
  assert.equal(t("found", { n: 3 }), "Found 3 jobs that fit.");
  assert.equal(currentLocale(), "en");
});

test("a missing key returns the key and logs once", () => {
  const warn = console.warn;
  const calls = [];
  console.warn = (m) => calls.push(m);
  try {
    assert.equal(t("no.such.key"), "no.such.key");
    assert.equal(t("no.such.key"), "no.such.key");
  } finally {
    console.warn = warn;
  }
  assert.equal(calls.length, 1);
});

test("pt-BR loads", async () => {
  await loadLocale("pt-BR");
  assert.equal(currentLocale(), "pt-BR");
  assert.match(t("found", { n: 3 }), /3/);
});
