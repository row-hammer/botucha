"use client";

import { Badge } from "@/components/ui/badge";
import { useT } from "@/lib/i18n";
import type { StepStatus, TraceSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const outcomeTone: Record<string, string> = {
  sent: "bg-ok/15 text-ok border-ok/30",
  fallback: "bg-warn/15 text-warn border-warn/30",
  canned: "bg-bad/15 text-bad border-bad/30",
  error: "bg-bad/15 text-bad border-bad/30",
  skipped: "bg-muted text-muted-foreground",
  running: "bg-chart-1/15 text-chart-1 border-chart-1/30",
};

export const statusTone: Record<StepStatus, string> = {
  ok: "border-ok/60 bg-ok/10",
  rejected: "border-bad/70 bg-bad/10",
  skipped: "border-border bg-muted/50 opacity-70",
  error: "border-warn/70 bg-warn/10",
};

export const statusText: Record<StepStatus, string> = {
  ok: "text-ok",
  rejected: "text-bad",
  skipped: "text-muted-foreground",
  error: "text-warn",
};

export function OutcomeBadge({ outcome }: { outcome: TraceSummary["outcome"] }) {
  const t = useT();
  const o = outcome ?? "running";
  return (
    <Badge variant="outline" className={cn(outcomeTone[o])}>
      {t(`thinking.outcome.${o}`)}
    </Badge>
  );
}

export function useTriggerLabel() {
  const t = useT();
  return (trigger: string) =>
    trigger
      .split("+")
      .filter(Boolean)
      .map((part) => {
        const [kind, arg] = part.split(":");
        if (kind === "keyword") return t("thinking.trigger.keyword", { k: arg ?? "" });
        if (kind === "random") return t("thinking.trigger.random", { n: (arg ?? "").replace("1/", "") });
        return t(`thinking.trigger.${kind}`);
      })
      .join(" + ") || "–";
}
