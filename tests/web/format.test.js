import { test } from "node:test";
import assert from "node:assert/strict";

const { safeUrl, timeAgo, salary, scoreLabel, sourceName } = await import("../../src/jobscout/web/js/format.js");

const en = { ago_now: "just now", ago_m: "{n}m ago", ago_h: "{n}h ago", ago_d: "{n}d ago", ago_w: "{n}w ago" };
const t = (key, params) => (en[key] || key).replace(/\{(\w+)\}/g, (w, n) => (params && n in params ? params[n] : w));

test("safeUrl keeps http and https only", () => {
  assert.equal(safeUrl("javascript:alert(1)"), null);
  assert.equal(safeUrl("JaVaScRiPt:alert(1)"), null);
  assert.equal(safeUrl("data:text/html,<script>alert(1)</script>"), null);
  assert.equal(safeUrl("https://x.io/a"), "https://x.io/a");
  assert.equal(safeUrl("http://x.io/a?b=1"), "http://x.io/a?b=1");
  assert.equal(safeUrl("not a url"), null);
  assert.equal(safeUrl(""), null);
  assert.equal(safeUrl(null), null);
});

test("timeAgo", () => {
  const now = new Date("2026-11-08T12:00:00Z");
  assert.equal(timeAgo("2026-11-06T12:00:00Z", now, t), "2d ago");
  assert.equal(timeAgo("2026-11-08T07:00:00Z", now, t), "5h ago");
  assert.equal(timeAgo("2026-11-08T11:45:00Z", now, t), "15m ago");
  assert.equal(timeAgo("2026-10-18T12:00:00Z", now, t), "3w ago");
  assert.equal(timeAgo("2026-11-08T11:59:40Z", now, t), "just now");
  // The API's naive timestamps are UTC.
  assert.equal(timeAgo("2026-11-08T07:00:00", now, t), "5h ago");
  assert.equal(timeAgo(null, now, t), null);
});

test("salary is omitted without bounds and compact with them", () => {
  assert.equal(salary({ salary_min: null, salary_max: null, salary_currency: "USD" }, "en"), null);
  assert.equal(salary({ salary_min: 6000, salary_max: 8000, salary_currency: "BRL" }, "en"), "R$ 6–8 mil");
  assert.equal(salary({ salary_min: 40000, salary_max: 55000, salary_currency: "USD" }, "en"), "$40–55k");
  assert.equal(salary({ salary_min: 40000, salary_max: null, salary_currency: "USD" }, "en"), "$40k");
  assert.equal(salary({ salary_min: 6500, salary_max: 8000, salary_currency: "BRL" }, "pt-BR"), "R$ 6,5–8 mil");
  assert.equal(salary({ salary_min: 50000, salary_max: 60000, salary_currency: "EUR" }, "pt-BR"), "€50–60 mil");
  assert.equal(salary({ salary_min: 30, salary_max: 45, salary_currency: "USD" }, "en"), "$30–45");
  assert.equal(salary({ salary_min: 70000, salary_max: 80000, salary_currency: null }, "en"), "70–80k");
  assert.equal(salary({ salary_min: 5000, salary_max: 5000, salary_currency: "CHF" }, "en"), "CHF 5k");
});

test("scoreLabel and sourceName", () => {
  assert.equal(scoreLabel(92), "92%");
  assert.equal(scoreLabel(null), null);
  assert.equal(sourceName("linkedin"), "LinkedIn");
  assert.equal(sourceName("himalayas"), "Himalayas");
});
