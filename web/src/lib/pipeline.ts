// Pure helpers for the Pipeline page. No runtime imports so node --test can load it directly.
import type { Pipeline, Progress } from "./types.ts";

export const MAX_ATTEMPTS = 2; // botucha/brain.py tries the model twice
export const LIVE_STAGES = ["context", "retrieval", "prompt", "generation", "filter", "send"] as const;
export type LiveStage = (typeof LIVE_STAGES)[number];

export type NodeKind = "trigger" | "ok" | "warn" | "bad" | "muted";

const stageRank = (id: string) => {
  if (id.startsWith("trigger:")) return 0;
  if (id.startsWith("out:")) return 99;
  const m = /^a(\d+):/.exec(id);
  return m ? Number(m[1]) : 50;
};

export function nodeKind(id: string): NodeKind {
  const [stage, what] = id.split(":");
  if (stage === "trigger") return "trigger";
  if (stage === "out") return what === "sent" ? "ok" : what === "fallback" ? "warn" : "muted";
  if (what === "ok") return "ok";
  if (what === "error") return "warn";
  return "bad";
}

const severity: Record<NodeKind, number> = { trigger: 0, ok: 1, warn: 2, bad: 3, muted: 4 };

/** Recharts Sankey wants nodes as an array and links by index. Order: stage, then passes before failures. */
export function toSankey(p: Pick<Pipeline, "nodes" | "links">) {
  const nodes = [...p.nodes]
    .sort(
      (a, b) =>
        stageRank(a.id) - stageRank(b.id) ||
        severity[nodeKind(a.id)] - severity[nodeKind(b.id)] ||
        b.n - a.n ||
        a.id.localeCompare(b.id),
    )
    .map((n) => ({ name: n.id, n: n.n }));
  const index = new Map(nodes.map((n, i) => [n.name, i]));
  const links = p.links
    .filter((l) => index.has(l.source) && index.has(l.target))
    .map((l) => ({ source: index.get(l.source) as number, target: index.get(l.target) as number, value: l.value }));
  return { nodes, links };
}

/** What a running reply is doing now, from the last step it finished. */
export function liveStage(last: Progress["last"]): { stage: LiveStage; attempt: number } {
  const attempt = Number(/\d+/.exec(last.name ?? "")?.[0] ?? 1);
  const next = (more: boolean) =>
    more && attempt < MAX_ATTEMPTS
      ? { stage: "generation" as const, attempt: attempt + 1 }
      : { stage: "send" as const, attempt };
  switch (last.kind) {
    case "context":
      return { stage: "retrieval", attempt: 1 };
    case "retrieval":
      return { stage: "prompt", attempt: 1 };
    case "prompt":
      return { stage: "generation", attempt: 1 };
    case "generation":
      return last.status === "error" ? next(true) : { stage: "filter", attempt };
    case "filter":
      return last.status === "ok" ? { stage: "send", attempt } : next(true);
    default:
      return { stage: "send", attempt };
  }
}

export function pct(part: number, whole: number): string {
  return whole > 0 ? `${Math.round((part / whole) * 100)}%` : "–";
}
