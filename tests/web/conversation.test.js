import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fakeDocument, findElement } from "./fake-dom.js";

globalThis.document = fakeDocument;
const { renderEntries } = await import("../../src/jobscout/web/js/conversation.js");
const { buildTranscript } = await import("../../src/jobscout/web/js/transcript.js");
const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));

test("the skills row stays in the summary with no skill, so its pencil can add one", () => {
  const base = load("search-ready.json");
  const search = { ...base, summary: { ...base.summary, skills: [] } };
  const host = fakeDocument.createElement("div");
  renderEntries(buildTranscript(search), search, { sources: [] }, {}).forEach((n) => host.appendChild(n));
  const row = findElement(host, (el) => el.getAttribute("data-row") === "skills");
  assert.ok(row);
  assert.ok(row.textContent.includes("dont_mind"));
  assert.ok(findElement(row, (el) => el.getAttribute("data-edit") === "skills"));
});
