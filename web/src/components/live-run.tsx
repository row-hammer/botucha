"use client";

import { Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useTriggerLabel } from "@/components/trace-bits";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { useT } from "@/lib/i18n";
import { useLive } from "@/lib/live";
import { LIVE_STAGES, liveStage } from "@/lib/pipeline";
import type { Progress } from "@/lib/types";
import { cn } from "@/lib/utils";

const STUCK_S = 600; // same as the server: an unfinished run this old was cut short by a restart

function useNow(ms: number) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

function Run({ p, now }: { p: Progress; now: number }) {
  const t = useT();
  const trig = useTriggerLabel();
  const { stage, attempt } = liveStage(p.last);
  const at = LIVE_STAGES.indexOf(stage);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <Loader2 className="size-4 animate-spin text-chart-1" />
        <Link href={`/thinking/?id=${p.id}`} className="font-medium hover:underline">
          {p.kind === "reply" ? (p.user_name ?? "–") : t(`thinking.kind.${p.kind}`)}
        </Link>
        <span className="text-muted-foreground">{trig(p.trigger)}</span>
        <span className="text-muted-foreground tabular-nums">{Math.max(0, Math.round(now - p.started))} s</span>
        {attempt > 1 ? (
          <Badge variant="outline" className="border-warn/40 bg-warn/10 text-warn">
            {t("pipeline.live.retry", { n: attempt })}
          </Badge>
        ) : null}
      </div>
      {p.kind === "reply" ? (
        <ol className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
          {LIVE_STAGES.map((s, i) => (
            <li
              key={s}
              aria-current={i === at ? "step" : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs",
                i < at && "border-ok/40 bg-ok/10 text-ok",
                i === at && "animate-pulse border-chart-1/60 bg-chart-1/10 font-medium text-chart-1",
                i > at && "text-muted-foreground",
              )}
            >
              {i < at ? <Check className="size-3 shrink-0" /> : null}
              <span className="truncate">{t(`step.${s}`)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-muted-foreground text-xs">{t(`step.${p.last.kind}`)}</p>
      )}
    </div>
  );
}

/** What Botucha is doing right now, from the live progress events. */
export function LiveRun() {
  const t = useT();
  const running = useLive((s) => s.running);
  const connected = useLive((s) => s.connected);
  const now = useNow(1000);
  const runs = Object.values(running)
    .filter((p) => now - p.started < STUCK_S)
    .sort((a, b) => a.started - b.started);
  return (
    <Card className="py-4">
      <CardContent className="flex flex-col gap-4 px-4">
        <div className="flex items-center gap-2 font-medium text-sm">
          <span className={cn("size-2 rounded-full", connected ? "bg-ok" : "bg-muted-foreground")} />
          {t("pipeline.live.title")}
        </div>
        {runs.length ? (
          runs.map((p) => <Run key={p.id} p={p} now={now} />)
        ) : (
          <p className="text-muted-foreground text-sm">
            {connected ? t("pipeline.live.idle") : t("pipeline.live.offline")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
