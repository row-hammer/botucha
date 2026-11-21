// Layout for the People graph. Linked people (relations and co-mentions) are laid out left to right
// by dagre with room between columns for relation labels; people with no links go in a grid below.
// Pure (only dagre), so node --test can load it directly.
import dagre from "@dagrejs/dagre";
import type { PeopleGraph } from "./types.ts";

export const NODE_W = 220;
export const NODE_H = 56;
const GAP = 40; // between grid cells and between the graph and the grid
type XY = { x: number; y: number };

export function layoutPeople(graph: PeopleGraph, saved: Record<string, XY> = {}): Record<string, XY> {
  const links = [
    ...graph.relations.map((r) => [r.a, r.b] as const),
    ...graph.comentions.map((c) => [c.a, c.b] as const),
  ].filter(([a, b]) => a !== b);
  const linked = new Set(links.flat());
  const ids = graph.people.map((p) => p.id).sort((a, b) => a - b); // stable input, stable layout
  const out: Record<string, XY> = {};

  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "LR", nodesep: 50, ranksep: 150, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const id of ids) if (linked.has(id)) g.setNode(String(id), { width: NODE_W, height: NODE_H });
  links.forEach(([a, b], i) => {
    if (g.hasNode(String(a)) && g.hasNode(String(b))) g.setEdge(String(a), String(b), {}, `e${i}`);
  });
  let bottom = -GAP;
  let width = 0;
  if (g.nodeCount()) {
    dagre.layout(g);
    for (const id of g.nodes()) {
      const n = g.node(id);
      out[id] = { x: Math.round(n.x - NODE_W / 2), y: Math.round(n.y - NODE_H / 2) }; // dagre gives centres
      bottom = Math.max(bottom, out[id].y + NODE_H);
      width = Math.max(width, out[id].x + NODE_W);
    }
  }

  const loners = ids.filter((id) => !linked.has(id));
  const cols = Math.max(1, Math.min(loners.length, Math.floor(Math.max(width, 4 * NODE_W) / (NODE_W + GAP))));
  loners.forEach((id, i) => {
    out[id] = { x: (i % cols) * (NODE_W + GAP), y: bottom + GAP * 2 + Math.floor(i / cols) * (NODE_H + GAP) };
  });

  for (const [id, xy] of Object.entries(saved)) if (id in out) out[id] = xy; // a dragged box stays put
  return out;
}
