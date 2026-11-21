import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// Review finding: a copy-pasted listener parsed and stored every status event twice (two renders per event).
test("each live event type has exactly one listener", () => {
  const src = readFileSync(new URL("../src/lib/live.ts", import.meta.url), "utf8");
  const kinds = [...src.matchAll(/addEventListener\("(\w+)"/g)].map((m) => m[1]);
  const twice = kinds.filter((k, i) => kinds.indexOf(k) !== i);
  assert.deepEqual(twice, []);
  for (const k of ["open", "error", "status", "progress", "trace"]) assert.ok(kinds.includes(k), k);
});
