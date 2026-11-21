// Pure layout for the step graph: one column per pipeline stage, one row per generation attempt.
// No runtime imports so node --test can load it directly.
import type { Edge, Node } from "@xyflow/react";
import type { Step } from "./types.ts";

export const COL_W = 260;
export const ROW_H = 140;
const COLUMN: Record<string, number> = { context: 0, retrieval: 1, prompt: 2, generation: 3, filter: 4, send: 5 };

export interface StepNodeData extends Record<string, unknown> {
  step: Step;
}

function attemptRow(step: Step): number {
  const m = /(\d+)/.exec(step.name ?? "");
  return m ? Number(m[1]) - 1 : 0;
}

export function layoutTrace(steps: Step[]): { nodes: Node<StepNodeData>[]; edges: Edge[] } {
  const known = steps.every((s) => s.kind in COLUMN);
  let row = 0;
  const nodes = steps.map((step, i) => {
    let x: number;
    let y = 0;
    if (known) {
      if (step.kind === "generation" || step.kind === "filter") row = attemptRow(step);
      x = COLUMN[step.kind] * COL_W;
      y = step.kind === "send" || step.kind === "generation" || step.kind === "filter" ? row * ROW_H : 0;
    } else {
      x = i * COL_W;
    }
    return { id: String(step.id), type: "step", position: { x, y }, data: { step } };
  });
  const edges: Edge[] = [];
  for (let i = 1; i < steps.length; i++) {
    const prev = steps[i - 1];
    const cur = steps[i];
    const retry = cur.kind === "generation" && prev.status !== "ok";
    edges.push({
      id: `${prev.id}-${cur.id}`,
      source: String(prev.id),
      target: String(cur.id),
      type: "smoothstep",
      animated: retry,
      data: { retry },
      style: retry ? { strokeDasharray: "6 4", stroke: "var(--bad)" } : undefined,
    });
  }
  return { nodes, edges };
}
