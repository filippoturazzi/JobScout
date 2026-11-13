import { test } from "node:test";
import assert from "node:assert/strict";

const { parseRoute } = await import("../../src/jobscout/web/js/router.js");
const { apiQuery, filterCount, filterChips, clearFilters, pageInfo, PAGE_SIZE } = await import("../../src/jobscout/web/js/myjobsview.js");

const view = (query = "") => parseRoute(`#/my-jobs${query ? "?" + query : ""}`);

test("the API query carries the tab, the filters and the page", () => {
  assert.equal(apiQuery(view()), `tab=all&sort=score&offset=0&limit=${PAGE_SIZE}`);
  const q = new URLSearchParams(apiQuery(view("tab=saved&search=4&min=50&mode=remote,hybrid&source=indeed&since=7d&q=ai&sort=recent&page=3")));
  assert.equal(q.get("tab"), "saved");
  assert.equal(q.get("search_id"), "4");
  assert.equal(q.get("min_score"), "50");
  assert.deepEqual(q.getAll("mode"), ["remote", "hybrid"]);
  assert.deepEqual(q.getAll("source"), ["indeed"]);
  assert.equal(q.get("since"), "7d");
  assert.equal(q.get("q"), "ai");
  assert.equal(q.get("offset"), String(2 * PAGE_SIZE));
});

test("the filter count and chips leave out the tab, the search, the text and the sort", () => {
  const v = view("tab=saved&search=4&min=50&mode=remote&source=indeed,linkedin&q=ai&sort=recent");
  assert.equal(filterCount(v), 4);
  const chips = filterChips(v);
  assert.deepEqual(chips.map((c) => c.key), ["min", "mode:remote", "source:indeed", "source:linkedin"]);
  // A chip's view drops that one filter and goes back to the first page.
  assert.deepEqual(chips[2].without.sources, ["linkedin"]);
  assert.equal(chips[0].without.min, 0);
  assert.equal(filterCount(view("since=24h")), 1);
});

test("clearing the filters keeps the tab, the search, the text and the sort", () => {
  const cleared = clearFilters(view("tab=saved&search=4&min=50&mode=remote&since=7d&q=ai&sort=company&page=2"));
  assert.equal(filterCount(cleared), 0);
  assert.deepEqual([cleared.tab, cleared.search, cleared.q, cleared.sort, cleared.page], ["saved", 4, "ai", "company", 1]);
});

test("pageInfo says which rows show and whether there is a page either side", () => {
  assert.deepEqual(pageInfo(1, 0), { from: 0, to: 0, pages: 1, prev: false, next: false });
  assert.deepEqual(pageInfo(1, 45), { from: 1, to: 20, pages: 3, prev: false, next: true });
  assert.deepEqual(pageInfo(3, 45), { from: 41, to: 45, pages: 3, prev: true, next: false });
});
