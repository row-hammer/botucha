import assert from "node:assert/strict";
import { test } from "node:test";
import { liveStage, nodeKind, pct, toSankey } from "../src/lib/pipeline.ts";

const p = {
  nodes: [
    { id: "out:sent", n: 2 },
    { id: "a1:spelling", n: 2 },
    { id: "trigger:direct", n: 3 },
    { id: "a1:ok", n: 1 },
    { id: "a2:ok", n: 1 },
    { id: "out:fallback", n: 1 },
    { id: "a2:spelling", n: 1 },
  ],
  links: [
    { source: "trigger:direct", target: "a1:ok", value: 1 },
    { source: "trigger:direct", target: "a1:spelling", value: 2 },
    { source: "a1:ok", target: "out:sent", value: 1 },
    { source: "a1:spelling", target: "a2:ok", value: 1 },
    { source: "a1:spelling", target: "a2:spelling", value: 1 },
    { source: "a2:ok", target: "out:sent", value: 1 },
    { source: "a2:spelling", target: "out:fallback", value: 1 },
  ],
};

test("nodes are ordered by stage, passes before failures, and links point at those indices", () => {
  const s = toSankey(p);
  assert.deepEqual(
    s.nodes.map((n) => n.name),
    ["trigger:direct", "a1:ok", "a1:spelling", "a2:ok", "a2:spelling", "out:sent", "out:fallback"],
  );
  for (const l of s.links) assert.ok(s.nodes[l.source] && s.nodes[l.target]);
  const first = s.links.find((l) => s.nodes[l.target].name === "a1:spelling");
  assert.equal(first.value, 2);
});

test("node kinds drive colour", () => {
  assert.equal(nodeKind("trigger:direct"), "trigger");
  assert.equal(nodeKind("a1:ok"), "ok");
  assert.equal(nodeKind("a2:error"), "warn");
  assert.equal(nodeKind("a1:spelling"), "bad");
  assert.equal(nodeKind("out:sent"), "ok");
  assert.equal(nodeKind("out:fallback"), "warn");
  assert.equal(nodeKind("out:skipped"), "muted");
});

test("empty pipeline gives an empty sankey", () => {
  assert.deepEqual(toSankey({ nodes: [], links: [] }), { nodes: [], links: [] });
});

test("live stage: what the bot is doing after the last finished step", () => {
  const last = (kind, name = null, status = "ok") => ({ kind, name, status });
  assert.deepEqual(liveStage(last("context")), { stage: "retrieval", attempt: 1 });
  assert.deepEqual(liveStage(last("prompt")), { stage: "generation", attempt: 1 });
  assert.deepEqual(liveStage(last("generation", "attempt 1")), { stage: "filter", attempt: 1 });
  assert.deepEqual(liveStage(last("filter", "attempt 1", "rejected")), { stage: "generation", attempt: 2 });
  assert.deepEqual(liveStage(last("generation", "attempt 2", "error")), { stage: "send", attempt: 2 });
  assert.deepEqual(liveStage(last("filter", "attempt 2", "ok")), { stage: "send", attempt: 2 });
});

test("percent with denominator, never NaN", () => {
  assert.equal(pct(1, 4), "25%");
  assert.equal(pct(0, 0), "–");
});
