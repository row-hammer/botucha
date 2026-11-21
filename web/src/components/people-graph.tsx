"use client";

import {
  Background,
  type Connection,
  ConnectionMode,
  Controls,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo } from "react";
import { useT } from "@/lib/i18n";
import type { PeopleGraph, Person } from "@/lib/types";
import { cn } from "@/lib/utils";

const POS_KEY = "botucha.people.pos";
const SIDES = [
  ["t", Position.Top],
  ["r", Position.Right],
  ["b", Position.Bottom],
  ["l", Position.Left],
] as const;
type XY = { x: number; y: number };

function loadPos(): Record<string, XY> {
  try {
    return JSON.parse(localStorage.getItem(POS_KEY) ?? "{}");
  } catch {
    return {};
  }
}

function savePos(node: Node) {
  try {
    localStorage.setItem(POS_KEY, JSON.stringify({ ...loadPos(), [node.id]: node.position }));
  } catch {
    /* private window */
  }
}

/** Leave and enter on the sides facing each other, so edges don't loop around the nodes. */
function route(from: XY, to: XY): { sourceHandle: string; targetHandle: string } {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dy) > Math.abs(dx) * 0.6)
    return dy > 0 ? { sourceHandle: "s-b", targetHandle: "t-t" } : { sourceHandle: "s-t", targetHandle: "t-b" };
  return dx > 0 ? { sourceHandle: "s-r", targetHandle: "t-l" } : { sourceHandle: "s-l", targetHandle: "t-r" };
}

function PersonNode({ data, selected }: NodeProps) {
  const t = useT();
  const p = (data as { person: Person }).person;
  return (
    <div
      className={cn(
        "min-w-[120px] rounded-xl border-2 bg-card px-3 py-2 text-center text-card-foreground shadow-sm",
        p.user_id ? "border-chart-1/60" : "border-chart-5/60",
        selected && "ring-2 ring-ring",
      )}
    >
      {SIDES.map(([side, pos]) => (
        <Handle
          key={`t-${side}`}
          id={`t-${side}`}
          type="target"
          position={pos}
          className="!size-2 !border-0 !bg-transparent"
        />
      ))}
      <div className="font-medium text-sm">{p.name}</div>
      <div className="text-xs text-muted-foreground">
        {p.user_id ? t("people.member") : t("people.friend")} · {p.fact_count} {t("people.facts").toLowerCase()}
      </div>
      {SIDES.map(([side, pos]) => (
        <Handle
          key={`s-${side}`}
          id={`s-${side}`}
          type="source"
          position={pos}
          className={cn("!size-2.5 !border-2 !border-background !bg-muted-foreground", side !== "b" && "!opacity-0")}
        />
      ))}
    </div>
  );
}

const nodeTypes = { person: PersonNode };

export function PeopleGraphView({
  graph,
  selected,
  onSelect,
  onConnect,
}: {
  graph: PeopleGraph;
  selected: number | null;
  onSelect: (p: Person) => void;
  onConnect: (a: number, b: number) => void;
}) {
  const initial = useMemo<Node[]>(() => {
    const saved = loadPos();
    const n = graph.people.length || 1;
    const r = Math.max(300, n * 45);
    return graph.people.map((p, i) => ({
      id: String(p.id),
      type: "person",
      position: saved[p.id] ?? { x: r * Math.cos((2 * Math.PI * i) / n), y: r * Math.sin((2 * Math.PI * i) / n) },
      data: { person: p },
    }));
  }, [graph.people]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initial);
  useEffect(() => setNodes(initial), [initial, setNodes]);

  const edges = useMemo<Edge[]>(() => {
    const at = new Map(nodes.map((n) => [n.id, n.position]));
    const sides = (a: number, b: number) =>
      route(at.get(String(a)) ?? { x: 0, y: 0 }, at.get(String(b)) ?? { x: 0, y: 0 });
    return [
      ...graph.comentions.map((c) => ({
        id: `c${c.a}-${c.b}`,
        source: String(c.a),
        target: String(c.b),
        ...sides(c.a, c.b),
        selectable: false,
        style: { stroke: "var(--muted-foreground)", strokeDasharray: "4 4", opacity: 0.35, strokeWidth: 1 + c.n },
      })),
      ...graph.relations.map((r) => ({
        id: `r${r.id}`,
        source: String(r.a),
        target: String(r.b),
        ...sides(r.a, r.b),
        label: r.rel,
        selectable: false,
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--chart-1)" },
        style: { stroke: "var(--chart-1)", strokeWidth: 2 },
        labelStyle: { fontSize: 12, fontWeight: 500 },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 6,
      })),
    ];
  }, [graph, nodes]);

  return (
    <div className="h-[calc(100svh-9rem)] min-h-[420px] rounded-lg border bg-muted/20">
      <ReactFlow
        nodes={nodes.map((n) => ({ ...n, selected: n.id === String(selected) }))}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, node) => savePos(node)}
        onNodeClick={(_, n) => onSelect((n.data as { person: Person }).person)}
        onConnect={(c: Connection) => c.source !== c.target && onConnect(Number(c.source), Number(c.target))}
        connectionMode={ConnectionMode.Loose}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} size={1} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
