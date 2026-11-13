import { test } from "node:test";
import assert from "node:assert/strict";

const { parseRoute, myJobsPath } = await import("../../src/jobscout/web/js/router.js");

test("the plain routes parse, unknown ones are home", () => {
  assert.deepEqual(parseRoute(""), { name: "home" });
  assert.deepEqual(parseRoute("#/search/7"), { name: "search", id: 7 });
  assert.deepEqual(parseRoute("#/settings"), { name: "settings" });
  assert.deepEqual(parseRoute("#/nowhere"), { name: "home" });
});

const DEFAULT = { name: "my-jobs", tab: "all", search: null, open: null, min: 0, modes: [], sources: [], since: null, q: "", sort: "score", page: 1 };

test("my jobs defaults to the All tab with no filter", () => {
  assert.deepEqual(parseRoute("#/my-jobs"), DEFAULT);
});

test("my jobs reads the tab, the search and the filters from the query", () => {
  assert.deepEqual(parseRoute("#/my-jobs?tab=saved&search=2"), { ...DEFAULT, tab: "saved", search: 2 });
  assert.deepEqual(parseRoute("#/my-jobs?tab=dismissed"), { ...DEFAULT, tab: "dismissed" });
  assert.deepEqual(parseRoute("#/my-jobs?min=50&mode=remote,hybrid&source=indeed&since=7d&q=data%20eng&sort=recent&page=3"), {
    ...DEFAULT,
    min: 50,
    modes: ["remote", "hybrid"],
    sources: ["indeed"],
    since: "7d",
    q: "data eng",
    sort: "recent",
    page: 3,
  });
});

test("my jobs ignores what it does not know", () => {
  assert.deepEqual(parseRoute("#/my-jobs?tab=bogus&search=abc"), DEFAULT);
  assert.deepEqual(parseRoute("#/my-jobs?search=0&min=45&mode=space,remote&since=1y&sort=x&page=0"), { ...DEFAULT, modes: ["remote"] });
});

test("myJobsPath writes only what differs from the default, and round-trips", () => {
  assert.equal(myJobsPath(DEFAULT), "/my-jobs");
  assert.equal(myJobsPath({ ...DEFAULT, tab: "saved", search: 2 }), "/my-jobs?tab=saved&search=2");
  const view = { ...DEFAULT, min: 70, modes: ["onsite"], sources: ["linkedin", "indeed"], since: "24h", q: "ai", sort: "company", page: 2 };
  assert.deepEqual(parseRoute("#" + myJobsPath(view)), view);
});

test("my-jobs carries a match to open, which the path never writes", () => {
  assert.equal(parseRoute("#/my-jobs?tab=saved&open=7").open, 7);
  assert.equal(parseRoute("#/my-jobs?open=x").open, null);
  assert.equal(myJobsPath({ ...DEFAULT, open: 7 }), "/my-jobs");
});
