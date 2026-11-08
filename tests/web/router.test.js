import { test } from "node:test";
import assert from "node:assert/strict";

const { parseRoute, myJobsPath } = await import("../../src/jobscout/web/js/router.js");

test("the plain routes parse, unknown ones are home", () => {
  assert.deepEqual(parseRoute(""), { name: "home" });
  assert.deepEqual(parseRoute("#/search/7"), { name: "search", id: 7 });
  assert.deepEqual(parseRoute("#/settings"), { name: "settings" });
  assert.deepEqual(parseRoute("#/nowhere"), { name: "home" });
});

test("my jobs defaults to the All tab with no search filter", () => {
  assert.deepEqual(parseRoute("#/my-jobs"), { name: "my-jobs", tab: "all", search: null });
});

test("my jobs reads the tab and the search from the query", () => {
  assert.deepEqual(parseRoute("#/my-jobs?tab=saved&search=2"), { name: "my-jobs", tab: "saved", search: 2 });
  assert.deepEqual(parseRoute("#/my-jobs?tab=applied"), { name: "my-jobs", tab: "applied", search: null });
});

test("my jobs ignores a bad tab or search", () => {
  assert.deepEqual(parseRoute("#/my-jobs?tab=bogus&search=abc"), { name: "my-jobs", tab: "all", search: null });
  assert.deepEqual(parseRoute("#/my-jobs?search=0"), { name: "my-jobs", tab: "all", search: null });
});

test("myJobsPath writes only what differs from the default", () => {
  assert.equal(myJobsPath("all", null), "/my-jobs");
  assert.equal(myJobsPath("saved", null), "/my-jobs?tab=saved");
  assert.equal(myJobsPath("saved", 2), "/my-jobs?tab=saved&search=2");
  assert.equal(myJobsPath("all", 2), "/my-jobs?search=2");
});
