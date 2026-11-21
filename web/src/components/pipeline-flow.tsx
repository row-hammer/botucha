"use client";

import { ResponsiveContainer, Sankey } from "recharts";
import type { LinkProps, NodeProps } from "recharts/types/chart/Sankey";
import { useTriggerLabel } from "@/components/trace-bits";
import { useT } from "@/lib/i18n";
import { type NodeKind, nodeKind, toSankey } from "@/lib/pipeline";
import type { Pipeline } from "@/lib/types";

const fill: Record<NodeKind, string> = {
  trigger: "var(--chart-1)",
  ok: "var(--ok)",
  warn: "var(--warn)",
  bad: "var(--bad)",
  muted: "var(--muted-foreground)",
};

/** Human label for a pipeline node id such as "a1:spelling" or "out:fallback". */
export function useNodeLabel() {
  const t = useT();
  const trig = useTriggerLabel();
  return (id: string) => {
    const [stage, what = ""] = id.split(":", 2);
    const rest = id.slice(stage.length + 1);
    if (stage === "trigger") return rest === "unknown" ? t("pipeline.node.unknown") : trig(rest);
    if (stage === "out") return t(`thinking.outcome.${what}`);
    const n = stage.slice(1);
    if (what === "ok") return t("pipeline.node.passed", { n });
    if (what === "error") return t("pipeline.node.error", { n });
    if (what === "rejected") return t("pipeline.node.rejectedAny", { n });
    return t("pipeline.node.rejected", { n, check: t(`checks.${what}`) });
  };
}

export function PipelineFlow({ data, onSelect }: { data: Pipeline; onSelect: (node: string) => void }) {
  const label = useNodeLabel();
  const sankey = toSankey(data);

  const renderNode = ({ x, y, width, height, payload }: NodeProps) => {
    const id = String(payload.name);
    const n = (payload as unknown as { n: number }).n;
    return (
      // biome-ignore lint/a11y/useSemanticElements: an SVG group cannot be a <button>; keyboard handled below
      <g
        role="button"
        tabIndex={0}
        aria-label={`${label(id)}: ${n}`}
        className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-ring [&:focus-visible>rect]:stroke-2"
        onClick={() => onSelect(id)}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(id)}
      >
        <rect x={x} y={y} width={width} height={Math.max(height, 2)} rx={2} fill={fill[nodeKind(id)]} />
        <text
          x={x + width + 6}
          y={y + height / 2}
          dominantBaseline="middle"
          fontSize={12}
          fill="var(--foreground)"
          stroke="var(--card)"
          strokeWidth={3}
          paintOrder="stroke"
        >
          {label(id)} <tspan fill="var(--muted-foreground)">· {n}</tspan>
        </text>
      </g>
    );
  };

  const renderLink = (p: LinkProps) => {
    const target = String(p.payload.target.name);
    return (
      // biome-ignore lint/a11y/noStaticElementInteractions: the same drill-down is reachable from the node it points at
      <path
        d={`M${p.sourceX},${p.sourceY}C${p.sourceControlX},${p.sourceY} ${p.targetControlX},${p.targetY} ${p.targetX},${p.targetY}`}
        fill="none"
        stroke={fill[nodeKind(target)]}
        strokeWidth={Math.max(p.linkWidth, 1)}
        strokeOpacity={0.28}
        className="cursor-pointer transition-[stroke-opacity] hover:stroke-opacity-60"
        onClick={() => onSelect(target)}
      >
        <title>{`${label(String(p.payload.source.name))} → ${label(target)}: ${p.payload.value}`}</title>
      </path>
    );
  };

  return (
    <ResponsiveContainer>
      <Sankey
        data={sankey}
        node={renderNode}
        link={renderLink}
        nodeWidth={10}
        nodePadding={22}
        iterations={64}
        margin={{ top: 8, right: 190, bottom: 8, left: 4 }}
      />
    </ResponsiveContainer>
  );
}
