import { test } from "node:test";
import assert from "node:assert/strict";

const { createGuard } = await import("../../src/jobscout/web/js/guard.js");

test("a ticket is current until a newer one or an invalidation", () => {
  const g = createGuard();
  const a = g.next();
  assert.equal(g.isCurrent(a), true);
  const b = g.next();
  assert.equal(g.isCurrent(a), false);
  assert.equal(g.isCurrent(b), true);
  g.invalidate();
  assert.equal(g.isCurrent(b), false);
});
