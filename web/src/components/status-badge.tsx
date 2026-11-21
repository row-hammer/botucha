"use client";

import { Badge } from "@/components/ui/badge";
import { useT } from "@/lib/i18n";
import type { BotState } from "@/lib/types";
import { cn } from "@/lib/utils";

const tone: Record<BotState, string> = {
  active: "bg-ok/15 text-ok border-ok/30",
  inactive: "bg-muted text-muted-foreground",
  failed: "bg-bad/15 text-bad border-bad/30",
  activating: "bg-warn/15 text-warn border-warn/30",
  deactivating: "bg-warn/15 text-warn border-warn/30",
  unknown: "bg-muted text-muted-foreground",
};

export function StatusBadge({ state }: { state: BotState | undefined }) {
  const t = useT();
  const s = state ?? "unknown";
  return (
    <Badge variant="outline" className={cn("gap-1.5", tone[s])}>
      <span className={cn("size-1.5 rounded-full bg-current", s === "active" && "animate-pulse")} />
      {t(`status.${s}`)}
    </Badge>
  );
}
