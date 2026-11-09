import { test } from "node:test";
import assert from "node:assert/strict";
import { apiError, ApiError, api } from "../../src/jobscout/web/js/api.js";

test("apiError reads this API's 409 body", () => {
  const e = apiError(409, { detail: "Another search is running", code: "search_busy", search_id: 4 });
  assert.ok(e instanceof ApiError);
  assert.equal(e.status, 409);
  assert.equal(e.code, "search_busy");
  assert.equal(e.searchId, 4);
  assert.equal(e.detail, "Another search is running");
});

test("apiError reads FastAPI's validation body", () => {
  const e = apiError(422, { detail: [{ loc: ["body", "x"], msg: "field required", type: "missing" }] });
  assert.equal(e.code, null);
  assert.equal(e.searchId, null);
  assert.equal(typeof e.detail, "string");
  assert.match(e.detail, /field required/);
});

test("apiError survives a body that is not JSON", () => {
  const e = apiError(500, null);
  assert.equal(e.status, 500);
  assert.equal(e.code, null);
});

test("api returns null for 204 and throws ApiError otherwise", async () => {
  globalThis.fetch = async (url, opts) =>
    opts.method === "DELETE"
      ? { ok: true, status: 204, json: async () => { throw new Error("no body"); } }
      : { ok: false, status: 409, json: async () => ({ detail: "busy", code: "search_busy", search_id: 2 }) };
  assert.equal(await api.del("/searches/1"), null);
  await assert.rejects(api.post("/search", {}), (e) => e.code === "search_busy" && e.searchId === 2);
});
