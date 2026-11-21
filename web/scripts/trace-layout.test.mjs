import assert from "node:assert/strict";
import { test } from "node:test";
import { layoutTrace } from "../src/lib/trace-layout.ts";

const step = (seq, kind, name = null, status = "ok") => ({
  id: seq + 1,
  seq,
  kind,
  name,
  status,
  started: 0,
  duration_ms: 10,
  detail: {},
  has_prompt: false,
});

test("retry goes one row down and the send step follows the last attempt", () => {
  const steps = [
    step(0, "context"),
    step(1, "retrieval"),
    step(2, "prompt"),
    step(3, "generation", "attempt 1"),
    step(4, "filter", "attempt 1", "rejected"),
    step(5, "generation", "attempt 2"),
    step(6, "filter", "attempt 2"),
    step(7, "send"),
  ];
  const { nodes, edges } = layoutTrace(steps);
  const pos = Object.fromEntries(nodes.map((n) => [n.id, n.position]));
  assert.deepEqual(pos["6"], { x: 780, y: 140 }); // generation #2
  assert.deepEqual(pos["8"], { x: 1300, y: 140 }); // send
  assert.deepEqual(pos["4"], { x: 780, y: 0 }); // generation #1
  const dashed = edges.filter((e) => e.data?.retry);
  assert.equal(dashed.length, 1);
  assert.deepEqual([dashed[0].source, dashed[0].target], ["5", "6"]);
  assert.equal(edges.length, 7);
});

test("unknown step kinds (learning) are laid out left to right", () => {
  const { nodes } = layoutTrace([step(0, "extract"), step(1, "facts"), step(2, "slang")]);
  assert.deepEqual(
    nodes.map((n) => n.position.x),
    [0, 260, 520],
  );
});
