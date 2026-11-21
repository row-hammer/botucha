"use client";

import { AlertTriangle, Gauge, MessageSquare, ThumbsDown, ThumbsUp, Timer, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartCard } from "@/components/chart-card";
import { PageHeader } from "@/components/page-header";
import { StatCard } from "@/components/stat-card";
import { StatusBadge } from "@/components/status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { fmtMs, fmtNum, fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { onTrace, useLive } from "@/lib/live";
import type { Metrics } from "@/lib/types";

type Range = "24h" | "7d" | "30d";
const axis = { stroke: "var(--muted-foreground)", fontSize: 11, tickLine: false, axisLine: false };
const tooltipStyle = {
  contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "var(--muted-foreground)" },
};

export default function Overview() {
  const t = useT();
  const locale = useLocale();
  const status = useLive((s) => s.status);
  const [range, setRange] = useState<Range>("24h");
  const [m, setM] = useState<Metrics | null>(null);

  const load = useCallback(() => {
    api<Metrics>(`/api/metrics?range=${range}`)
      .then(setM)
      .catch(() => {});
  }, [range]);
  useEffect(() => {
    load();
    return onTrace(load);
  }, [load]);

  const tick = (ts: number) =>
    range === "24h"
      ? new Date(ts * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })
      : new Date(ts * 1000).toLocaleDateString(locale, { month: "short", day: "numeric" });
  const label = (ts: number) => fmtTime(ts, locale, true);
  const series = m?.series.map((s) => ({ ...s, label: tick(s.t) })) ?? [];
  const ratings = m?.ratings.map((r) => ({ ...r, label: tick(r.t) })) ?? [];
  const rejections = Object.entries(m?.rejections_by_filter ?? {}).map(([name, n]) => ({ name, n }));
  const noReplies = !m || m.cards.replies === 0;

  return (
    <>
      <PageHeader title={t("nav.overview")}>
        <Tabs value={range} onValueChange={(v) => setRange(v as Range)}>
          <TabsList>
            {(["24h", "7d", "30d"] as Range[]).map((r) => (
              <TabsTrigger key={r} value={r}>
                {t(`overview.range.${r}`)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </PageHeader>
      <div className="flex flex-col gap-4 p-4">
        <Card className="py-3">
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 text-sm">
            <StatusBadge state={status?.bot} />
            <span>
              <span className="text-muted-foreground">{t("status.model")}: </span>
              <span className="font-mono">{status?.model ?? "–"}</span>
            </span>
            {status?.started_at ? (
              <span>
                <span className="text-muted-foreground">{t("status.uptime")}: </span>
                {fmtTime(status.started_at, locale)}
              </span>
            ) : null}
            <span>{status?.enabled ? t("status.enabled") : t("status.disabled")}</span>
            {status && status.quiet_until * 1000 > Date.now() ? (
              <span>{t("status.quietUntil", { time: fmtTime(status.quiet_until, locale, false) })}</span>
            ) : null}
            {status?.last_error ? (
              <span className="flex min-w-0 items-center gap-1 text-bad">
                <AlertTriangle className="size-4 shrink-0" />
                <span className="truncate">
                  {t("status.lastError")}: {status.last_error}
                </span>
              </span>
            ) : null}
          </CardContent>
        </Card>

        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <StatCard label={t("overview.cards.replies")} value={fmtNum(m?.cards.replies)} icon={MessageSquare} />
          <StatCard label={t("overview.cards.median")} value={fmtMs(m?.cards.median_ms)} icon={Timer} />
          <StatCard
            label={t("overview.cards.toks")}
            value={m?.cards.tok_s == null ? "–" : t("units.toks", { n: fmtNum(m.cards.tok_s) })}
            icon={Zap}
          />
          <StatCard
            label={t("overview.cards.rejections")}
            value={fmtNum(m?.cards.rejections)}
            icon={Gauge}
            tone="text-warn"
          />
          <StatCard label={t("overview.cards.good")} value={fmtNum(m?.cards.good)} icon={ThumbsUp} tone="text-ok" />
          <StatCard label={t("overview.cards.bad")} value={fmtNum(m?.cards.bad)} icon={ThumbsDown} tone="text-bad" />
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard title={t("overview.charts.latency")} empty={noReplies} emptyText={t("overview.noData")}>
            <ResponsiveContainer>
              <LineChart data={series}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" {...axis} minTickGap={24} />
                <YAxis {...axis} tickFormatter={(v) => fmtMs(v)} width={56} />
                <Tooltip
                  {...tooltipStyle}
                  formatter={(v) => fmtMs(v as number)}
                  labelFormatter={(_, p) => (p?.[0] ? label(p[0].payload.t) : "")}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Line
                  type="monotone"
                  dataKey="p50_ms"
                  name={t("overview.charts.p50")}
                  stroke="var(--chart-1)"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey="p95_ms"
                  name={t("overview.charts.p95")}
                  stroke="var(--chart-4)"
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  strokeDasharray="4 3"
                />
              </LineChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard title={t("overview.charts.replies")} empty={noReplies} emptyText={t("overview.noData")}>
            <ResponsiveContainer>
              <BarChart data={series}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" {...axis} minTickGap={24} />
                <YAxis {...axis} allowDecimals={false} width={32} />
                <Tooltip
                  {...tooltipStyle}
                  cursor={{ fill: "var(--muted)" }}
                  labelFormatter={(_, p) => (p?.[0] ? label(p[0].payload.t) : "")}
                />
                <Bar
                  dataKey="replies"
                  name={t("overview.charts.replies")}
                  fill="var(--chart-2)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard
            title={t("overview.charts.rejections")}
            empty={rejections.length === 0}
            emptyText={t("overview.noData")}
          >
            <ResponsiveContainer>
              <BarChart data={rejections} layout="vertical">
                <CartesianGrid stroke="var(--border)" horizontal={false} />
                <XAxis type="number" {...axis} allowDecimals={false} />
                <YAxis type="category" dataKey="name" {...axis} width={72} tickFormatter={(v) => t(`checks.${v}`)} />
                <Tooltip {...tooltipStyle} cursor={{ fill: "var(--muted)" }} labelFormatter={(v) => t(`checks.${v}`)} />
                <Bar
                  isAnimationActive={false}
                  dataKey="n"
                  name={t("overview.cards.rejections")}
                  fill="var(--chart-3)"
                  radius={[0, 4, 4, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard
            title={t("overview.charts.ratings")}
            empty={!m || m.cards.good + m.cards.bad === 0}
            emptyText={t("overview.noData")}
          >
            <ResponsiveContainer>
              <BarChart data={ratings}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="label" {...axis} minTickGap={24} />
                <YAxis {...axis} allowDecimals={false} width={32} />
                <Tooltip
                  {...tooltipStyle}
                  cursor={{ fill: "var(--muted)" }}
                  labelFormatter={(_, p) => (p?.[0] ? label(p[0].payload.t) : "")}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar
                  isAnimationActive={false}
                  dataKey="good"
                  stackId="r"
                  name={t("overview.cards.good")}
                  fill="var(--ok)"
                />
                <Bar
                  isAnimationActive={false}
                  dataKey="bad"
                  stackId="r"
                  name={t("overview.cards.bad")}
                  fill="var(--bad)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>
      </div>
    </>
  );
}
