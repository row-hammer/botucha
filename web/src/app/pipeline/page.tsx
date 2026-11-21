"use client";

import { CircleCheck, MessageSquare, Repeat, Send, TriangleAlert, VolumeX } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ChartCard } from "@/components/chart-card";
import { LiveRun } from "@/components/live-run";
import { PageHeader } from "@/components/page-header";
import { PipelineFlow } from "@/components/pipeline-flow";
import { StageChart, StageShare } from "@/components/stage-chart";
import { StatCard } from "@/components/stat-card";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { onTrace } from "@/lib/live";
import { pct } from "@/lib/pipeline";
import type { Pipeline } from "@/lib/types";

type Range = "24h" | "7d" | "30d";

export default function PipelinePage() {
  const t = useT();
  const locale = useLocale();
  const router = useRouter();
  const [range, setRange] = useState<Range>("24h");
  const [p, setP] = useState<Pipeline | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    api<Pipeline>(`/api/pipeline?range=${range}`)
      .then((r) => {
        setP(r);
        setError(false);
      })
      .catch(() => setError(true));
  }, [range]);
  useEffect(() => {
    load();
    return onTrace(load);
  }, [load]);

  const tick = (ts: number) =>
    range === "24h"
      ? new Date(ts * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
      : new Date(ts * 1000).toLocaleDateString(locale, { month: "short", day: "numeric" });
  const drill = (node: string) => router.push(`/thinking/?path=${encodeURIComponent(node)}&range=${range}`);
  const r = p?.rates;
  const runs = r?.runs ?? 0;

  return (
    <>
      <PageHeader title={t("nav.pipeline")}>
        <Tabs value={range} onValueChange={(v) => setRange(v as Range)}>
          <TabsList>
            {(["24h", "7d", "30d"] as Range[]).map((x) => (
              <TabsTrigger key={x} value={x}>
                {t(`overview.range.${x}`)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </PageHeader>
      <div className="flex flex-col gap-4 p-4">
        {error ? (
          <p role="alert" className="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-bad text-sm">
            {t("common.loadFailed")}
          </p>
        ) : null}
        <LiveRun />

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <StatCard label={t("pipeline.cards.runs")} value={fmtNum(r?.runs)} icon={MessageSquare} />
          <StatCard
            label={t("pipeline.cards.firstTry")}
            value={pct(r?.first_try ?? 0, runs)}
            sub={r ? `${r.first_try}/${runs}` : undefined}
            icon={CircleCheck}
            tone="text-ok"
            href={`/thinking/?path=a1:ok&range=${range}`}
          />
          <StatCard
            label={t("pipeline.cards.sent")}
            value={pct(r?.sent ?? 0, runs)}
            sub={r ? `${r.sent}/${runs}` : undefined}
            icon={Send}
            href={`/thinking/?path=out:sent&range=${range}`}
          />
          <StatCard
            label={t("pipeline.cards.fallback")}
            value={pct(r?.fallback ?? 0, runs)}
            sub={r ? `${r.fallback}/${runs}` : undefined}
            icon={TriangleAlert}
            tone="text-warn"
            href={`/thinking/?path=out:fallback&range=${range}`}
          />
          <StatCard
            label={t("pipeline.cards.silent")}
            value={pct(r?.silent ?? 0, runs)}
            sub={r ? `${r.silent}/${runs}` : undefined}
            icon={VolumeX}
            tone="text-bad"
          />
          <StatCard label={t("pipeline.cards.attempts")} value={fmtNum(r?.avg_attempts, 2)} icon={Repeat} />
        </div>

        <Card className="gap-2">
          <CardHeader>
            <CardTitle className="text-sm">{t("pipeline.flow.title")}</CardTitle>
            <CardDescription className="text-xs">{t("pipeline.flow.hint")}</CardDescription>
          </CardHeader>
          <CardContent className="h-[380px] overflow-x-auto">
            {p?.nodes.length ? (
              <div className="h-full min-w-[640px]">
                <PipelineFlow data={p} onSelect={drill} />
              </div>
            ) : (
              <div className="grid h-full place-items-center text-muted-foreground text-sm">
                {p ? t("overview.noData") : t("common.loading")}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <ChartCard title={t("pipeline.stages.title")} empty={!runs} emptyText={t("overview.noData")}>
              {p ? <StageChart data={p.stages} tick={tick} /> : null}
            </ChartCard>
          </div>
          <Card className="gap-2">
            <CardHeader>
              <CardTitle className="text-sm">{t("pipeline.stages.share")}</CardTitle>
              <CardDescription className="text-xs">{t("pipeline.stages.shareHint")}</CardDescription>
            </CardHeader>
            <CardContent>
              {p && runs ? (
                <StageShare data={p.stages} />
              ) : (
                <p className="text-muted-foreground text-sm">{t("overview.noData")}</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
