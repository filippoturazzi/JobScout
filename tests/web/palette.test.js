import { test } from "node:test";
import assert from "node:assert/strict";

const { paletteResults, fold } = await import("../../src/jobscout/web/js/palette.js");

const searches = [
  { id: 1, title: "Estágio em dados · remoto", match_count: 15 },
  { id: 2, title: "Dev júnior presencial · SP", match_count: 22 },
];
const saved = [
  { match: { id: 7, score: 45, job: { title: "Python Junior Developer", company: "BairesDev" } } },
  { match: { id: 8, score: 70, job: { title: "Pessoa Desenvolvedora de IA", company: "BIP" } } },
];

test("fold ignores case and accents", () => {
  assert.equal(fold("Estágio JÚNIOR"), "estagio junior");
});

test("an empty query lists the searches and the saved jobs as they are", () => {
  const groups = paletteResults("", searches, saved);
  assert.deepEqual(groups.map((g) => g.name), ["searches", "saved"]);
  assert.deepEqual(groups[0].items.map((i) => i.href), ["#/search/1", "#/search/2"]);
  assert.deepEqual(groups[1].items.map((i) => i.href), ["#/my-jobs?tab=saved&open=7", "#/my-jobs?tab=saved&open=8"]);
  assert.equal(groups[1].items[0].title, "Python Junior Developer · BairesDev");
});

test("a query keeps what matches its title or company, without accents, and drops empty groups", () => {
  const groups = paletteResults("junior", searches, saved);
  assert.deepEqual(groups.map((g) => g.items.map((i) => i.id)), [[2], [7]]);
  assert.deepEqual(paletteResults("bip", searches, saved).map((g) => g.name), ["saved"]);
  assert.deepEqual(paletteResults("zzz", searches, saved), []);
});

test("each group shows at most five", () => {
  const many = Array.from({ length: 8 }, (_, i) => ({ id: i + 1, title: `Search ${i}`, match_count: 0 }));
  assert.equal(paletteResults("", many, [])[0].items.length, 5);
});
