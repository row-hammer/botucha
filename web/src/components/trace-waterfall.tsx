"use client";

import { statusText } from "@/components/trace-bits";
import { fmtMs } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Step, TraceSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const barTone: Record<string, string> = {
  ok: "bg-ok",
  rejected: "bg-bad",
  skipped: "bg-muted-foreground",
  error: "bg-warn",
};

export function TraceWaterfall({
  trace,
  steps,
  selected,
  onSelect,
}: {
  trace: TraceSummary;
  steps: Step[];
  selected: number | null;
  onSelect: (s: Step) => void;
}) {
  const t = useT();
  const total = Math.max(
    trace.duration_ms ?? 0,
    ...steps.map((s) => (s.started - trace.started) * 1000 + s.duration_ms),
    1,
  );
  return (
    <div className="flex flex-col gap-1 rounded-lg border p-3">
      {steps.map((s) => {
        const offset = Math.max(0, (s.started - trace.started) * 1000);
        return (
          <button
            type="button"
            key={s.id}
            onClick={() => onSelect(s)}
            className={cn(
              "grid grid-cols-[9rem_1fr_4.5rem] items-center gap-3 rounded-none px-1 py-0.5 text-left text-xs hover:bg-muted",
              selected === s.id && "bg-muted",
            )}
          >
            <span className="truncate">
              {t(`step.${s.kind}`)}
              {s.name ? <span className="text-muted-foreground"> #{s.name.replace(/\D/g, "")}</span> : null}
            </span>
            <span className="relative h-3 rounded-none bg-muted/60">
              <span
                className={cn("absolute top-0 h-3 rounded-none", barTone[s.status])}
                style={{ left: `${(offset / total) * 100}%`, width: `max(2px, ${(s.duration_ms / total) * 100}%)` }}
              />
            </span>
            <span className={cn("text-right tabular-nums", statusText[s.status])}>{fmtMs(s.duration_ms)}</span>
          </button>
        );
      })}
      <div className="mt-1 text-right text-muted-foreground text-xs">
        {t("thinking.total", { t: fmtMs(trace.duration_ms) })}
      </div>
    </div>
  );
}
