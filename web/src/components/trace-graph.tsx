"use client";

import { Background, Controls, Handle, type NodeProps, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { statusText, statusTone } from "@/components/trace-bits";
import { fmtMs } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { layoutTrace, type StepNodeData } from "@/lib/trace-layout";
import type { Step } from "@/lib/types";
import { cn } from "@/lib/utils";

function summary(step: Step, t: (k: string, v?: Record<string, string | number>) => string): string {
  const d = step.detail as Record<string, unknown>;
  switch (step.kind) {
    case "retrieval":
      return `${(d.facts as unknown[] | undefined)?.length ?? 0} ${t("sections.facts")} · ${(d.chunks as unknown[] | undefined)?.length ?? 0} ${t("sections.chunks")}`;
    case "prompt":
      return t("thinking.panel.tokens", { n: Number(d.approx_tokens ?? 0) });
    case "generation":
      return d.tok_s ? `${Number(d.eval_count ?? 0)} tok · ${Number(d.tok_s).toFixed(1)} tok/s` : String(d.error ?? "");
    case "filter": {
      const failed = ((d.checks as { name: string; ok: boolean }[] | undefined) ?? []).filter((c) => !c.ok);
      return failed.length ? failed.map((c) => t(`checks.${c.name}`)).join(", ") : t("thinking.panel.passed");
    }
    case "context":
      return `${Number(d.history ?? 0)} ${t("sections.history")}`;
    case "send":
      return `${(d.msg_ids as unknown[] | undefined)?.length ?? 0} msg`;
    case "facts":
    case "slang":
      return `+${(d.added as unknown[] | undefined)?.length ?? 0} / −${(d.rejected as unknown[] | undefined)?.length ?? 0}`;
    default:
      return "";
  }
}

function StepNode({ data, selected }: NodeProps) {
  const t = useT();
  const { step, total } = data as StepNodeData & { total: number };
  const share = total ? Math.max(2, Math.min(100, (step.duration_ms / total) * 100)) : 0;
  return (
    <div
      className={cn(
        "w-[210px] rounded-lg border-2 bg-card px-3 py-2 text-card-foreground shadow-sm transition-shadow",
        statusTone[step.status],
        selected && "ring-2 ring-ring",
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-2 !border-0 !bg-muted-foreground" />
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-sm">
          {t(`step.${step.kind}`)}
          {step.name ? (
            <span className="ml-1 text-muted-foreground text-xs">#{step.name.replace(/\D/g, "")}</span>
          ) : null}
        </span>
        <span className={cn("text-xs", statusText[step.status])}>{t(`stepStatus.${step.status}`)}</span>
      </div>
      <div className="mt-0.5 truncate text-muted-foreground text-xs">{summary(step, t) || " "}</div>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-chart-1" style={{ width: `${share}%` }} />
        </div>
        <span className="text-[11px] tabular-nums text-muted-foreground">{fmtMs(step.duration_ms)}</span>
      </div>
      <Handle type="source" position={Position.Right} className="!size-2 !border-0 !bg-muted-foreground" />
    </div>
  );
}

const nodeTypes = { step: StepNode };

export function TraceGraph({
  steps,
  totalMs,
  selected,
  onSelect,
}: {
  steps: Step[];
  totalMs: number;
  selected: number | null;
  onSelect: (s: Step) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const l = layoutTrace(steps);
    return {
      nodes: l.nodes.map((n) => ({ ...n, selected: n.data.step.id === selected, data: { ...n.data, total: totalMs } })),
      edges: l.edges,
    };
  }, [steps, totalMs, selected]);
  return (
    <div className="h-[360px] rounded-lg border bg-muted/20">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => onSelect((n.data as StepNodeData).step)}
        minZoom={0.3}
      >
        <Background gap={20} size={1} color="var(--border)" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
