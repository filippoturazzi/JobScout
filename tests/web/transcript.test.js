import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const { buildTranscript, gotitWhat, answerLabel } = await import("../../src/jobscout/web/js/transcript.js");
const load = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));
const en = {
  level_junior: "Junior", dont_mind: "Don't mind", mode_remote: "Remote", mode_hybrid: "Hybrid",
  anywhere_in: "Anywhere in {country}", anywhere: "Anywhere", abroad_not: "Abroad, not {country}",
};
const t = (key, params) => (en[key] || key).replace(/\{(\w+)\}/g, (w, n) => (params && n in params ? params[n] : w));

test("paragraph, then got-it, then answered questions, then the active one", () => {
  const s = load("search-asking.json");
  const kinds = buildTranscript(s).map((e) => e.kind + (e.question ? `:${e.question.id}` : ""));
  assert.deepEqual(kinds, ["user", "gotit", "question:level", "user", "question:work_modes"]);
  const entries = buildTranscript(s);
  assert.equal(entries[2].active, false);
  assert.equal(entries[2].answered.choice, "junior");
  assert.equal(entries[4].active, true);
  assert.equal(entries[1].asking, true);
});

test("refinements follow the paragraph as user entries", () => {
  const s = { ...load("search-ready.json"), refinements: ["only hybrid"] };
  const entries = buildTranscript(s);
  assert.deepEqual(entries.slice(0, 2).map((e) => e.text), [s.paragraph, "only hybrid"]);
  assert.equal(entries[2].kind, "gotit");
});

test("a reading error replaces the got-it line", () => {
  const s = { ...load("search-ready.json"), reading: null, reading_error: "ValueError: boom", asked: [], answers: {} };
  const entries = buildTranscript(s);
  assert.deepEqual(entries.map((e) => e.kind), ["user", "error"]);
  assert.equal(entries[1].text, "ValueError: boom");
});

test("with no question pending the summary closes the transcript", () => {
  const entries = buildTranscript(load("search-ready.json"));
  const last = entries[entries.length - 1];
  assert.equal(last.kind, "summary");
  assert.equal(last.summary.role, "AI Engineer");
  assert.equal(entries.filter((e) => e.kind === "question").length, 3);
  assert.equal(entries.filter((e) => e.kind === "user").length, 4);
});

test("answer labels", () => {
  assert.equal(answerLabel("work_modes", { choice: "pick", values: ["remote", "hybrid"] }, t), "Remote, Hybrid");
  assert.equal(answerLabel("city", { choice: "anywhere", values: [] }, t, { country: "Brazil" }), "Anywhere in Brazil");
  assert.equal(answerLabel("city", { choice: "city", values: ["Recife"] }, t), "Recife");
  assert.equal(answerLabel("level", { choice: "any", values: [] }, t), "Don't mind");
  assert.equal(answerLabel("level", { choice: "junior", values: [] }, t), "Junior");
  assert.equal(answerLabel("location", { choice: "abroad", values: ["Brazil"] }, t), "Abroad, not Brazil");
  assert.equal(answerLabel("skills", { choice: "pick", values: ["Python", "RAG"] }, t), "Python, RAG");
});

test("got-it place reads city, country, anywhere and abroad", () => {
  const base = load("search-ready.json");
  const place = (summary, answers = {}) => gotitWhat({ ...base, summary: { ...base.summary, ...summary }, answers }).place;
  assert.deepEqual(place({ city: "Recife" }), { kind: "city", name: "Recife" });
  assert.deepEqual(place({}), { kind: "country", name: "Brazil" });
  assert.deepEqual(place({ country: null }, { location: { choice: "anywhere", values: [] } }), { kind: "anywhere", name: null });
  assert.deepEqual(place({ country: null, abroad_from: "Brazil" }), { kind: "abroad", name: "Brazil" });
  assert.equal(place({ country: null }), null);
  assert.deepEqual(gotitWhat(base).skills, ["Python", "LangChain", "RAG"]);
});
