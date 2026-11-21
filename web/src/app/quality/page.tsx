"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ActivityHeatmap } from "@/components/activity-heatmap";
import { ChartCard } from "@/components/chart-card";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { fmtMs, fmtNum, fmtTime } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { onTrace } from "@/lib/live";
import { pct } from "@/lib/pipeline";
import type { Quality } from "@/lib/types";
import { cn } from "@/lib/utils";

type Range = "24h" | "7d" | "30d";
const axis = { stroke: "var(--muted-foreground)", fontSize: 11, tickLine: false, axisLine: false };
const tooltip = {
  cursor: { fill: "var(--muted)" },
  contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
};

function Empty({ text }: { text: string }) {
  return <p className="py-6 text-center text-muted-foreground text-sm">{text}</p>;
}

function ContextMeter({ c }: { c: Quality["context"] }) {
  const t = useT();
  const rows: [string, number | null][] = [
    ["p50", c.p50],
    ["p95", c.p95],
    ["max", c.max],
  ];
  return (
    <div className="flex flex-col gap-4">
      {rows.map(([k, v]) => (
        <div key={k} className="flex flex-col gap-1">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">{t(`quality.context.${k}`)}</span>
            <span className="tabular-nums">
              {v == null ? "–" : t("quality.context.tokens", { n: Math.round(v).toLocaleString() })}{" "}
              <span className="text-muted-foreground">{v == null ? "" : pct(v, c.limit)}</span>
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={cn("h-full rounded-full", v != null && v / c.limit > 0.85 ? "bg-bad" : "bg-chart-1")}
              style={{ width: `${v == null ? 0 : Math.min(100, (v / c.limit) * 100)}%` }}
            />
          </div>
        </div>
      ))}
      <dl className="grid grid-cols-3 gap-2 border-t pt-3 text-center">
        {(["history", "facts", "chunks"] as const).map((k) => (
          <div key={k}>
            <dd className="font-semibold tabular-nums">{fmtNum(c[k])}</dd>
            <dt className="text-muted-foreground text-xs leading-tight">{t(`quality.context.${k}`)}</dt>
          </div>
        ))}
      </dl>
      <p className="text-muted-foreground text-xs">{t("quality.context.limit", { n: c.limit.toLocaleString() })}</p>
    </div>
  );
}

export default function QualityPage() {
  const t = useT();
  const locale = useLocale();
  const [range, setRange] = useState<Range>("7d");
  const [q, setQ] = useState<Quality | null>(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    api<Quality>(`/api/quality?range=${range}`)
      .then((r) => {
        setQ(r);
        setError(false);
      })
      .catch(() => setError(true));
  }, [range]);
  useEffect(() => {
    load();
    return onTrace(load);
  }, [load]);

  const attempts = Object.entries(q?.attempts ?? {}).map(([n, v]) => ({ name: t("quality.attempts.n", { n }), v }));
  const triggers = Object.entries(q?.triggers ?? {}).map(([k, v]) => ({
    name: ["keyword", "random", "unknown"].includes(k) ? t(`quality.triggers.${k}`) : t(`thinking.trigger.${k}`),
    v,
  }));
  const noData = t("overview.noData");

  return (
    <>
      <PageHeader title={t("nav.quality")}>
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

        <div className="grid gap-4 xl:grid-cols-5">
          <Card className="gap-2 xl:col-span-3">
            <CardHeader>
              <CardTitle className="text-sm">{t("quality.words.title")}</CardTitle>
              <CardDescription className="text-xs">{t("quality.words.hint")}</CardDescription>
            </CardHeader>
            <CardContent className="max-h-[420px] overflow-y-auto">
              {!q ? (
                <Empty text={t("common.loading")} />
              ) : q.words.length === 0 ? (
                <Empty text={noData} />
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("quality.words.word")}</TableHead>
                      <TableHead className="text-right">{t("quality.words.n")}</TableHead>
                      <TableHead className="hidden text-right sm:table-cell">{t("quality.words.replies")}</TableHead>
                      <TableHead className="text-right">{t("quality.words.last")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {q.words.map((w) => (
                      <TableRow key={w.word}>
                        <TableCell className="font-mono">{w.word}</TableCell>
                        <TableCell className="text-right tabular-nums">{w.n}</TableCell>
                        <TableCell className="hidden text-right tabular-nums sm:table-cell">{w.traces}</TableCell>
                        <TableCell className="text-right">
                          <Link href={`/thinking/?id=${w.trace_id}`} className="text-chart-1 hover:underline">
                            {fmtTime(w.last, locale)}
                          </Link>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
          <Card className="gap-2 xl:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">{t("quality.context.title")}</CardTitle>
              <CardDescription className="text-xs">{t("quality.context.hint")}</CardDescription>
            </CardHeader>
            <CardContent>{q?.context.replies ? <ContextMeter c={q.context} /> : <Empty text={noData} />}</CardContent>
          </Card>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard title={t("quality.attempts.title")} empty={!attempts.length} emptyText={noData}>
            <ResponsiveContainer>
              <BarChart data={attempts}>
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="name" {...axis} />
                <YAxis {...axis} allowDecimals={false} width={32} />
                <Tooltip {...tooltip} />
                <Bar
                  isAnimationActive={false}
                  dataKey="v"
                  name={t("quality.replies")}
                  maxBarSize={72}
                  fill="var(--chart-1)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
          <ChartCard title={t("quality.triggers.title")} empty={!triggers.length} emptyText={noData}>
            <ResponsiveContainer>
              <BarChart data={triggers} layout="vertical">
                <CartesianGrid stroke="var(--border)" horizontal={false} />
                <XAxis type="number" {...axis} allowDecimals={false} />
                <YAxis type="category" dataKey="name" {...axis} width={120} />
                <Tooltip {...tooltip} />
                <Bar
                  isAnimationActive={false}
                  dataKey="v"
                  name={t("quality.replies")}
                  maxBarSize={32}
                  fill="var(--chart-2)"
                  radius={[0, 4, 4, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </ChartCard>
        </div>

        <Card className="gap-2">
          <CardHeader>
            <CardTitle className="text-sm">{t("quality.people.title")}</CardTitle>
            <CardDescription className="text-xs">{t("quality.people.hint")}</CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            {!q?.people.length ? (
              <Empty text={q ? noData : t("common.loading")} />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("quality.people.name")}</TableHead>
                    <TableHead className="text-right">{t("quality.people.runs")}</TableHead>
                    <TableHead className="text-right">{t("quality.people.sent")}</TableHead>
                    <TableHead className="text-right">{t("quality.people.fallback")}</TableHead>
                    <TableHead className="text-right">{t("quality.people.silent")}</TableHead>
                    <TableHead className="text-right">{t("quality.people.median")}</TableHead>
                    <TableHead className="text-right">👍 / 👎</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {q.people.map((p) => (
                    <TableRow key={p.name}>
                      <TableCell className="font-medium">{p.name}</TableCell>
                      <TableCell className="text-right tabular-nums">{p.runs}</TableCell>
                      <TableCell className="text-right tabular-nums">{p.sent}</TableCell>
                      <TableCell className={cn("text-right tabular-nums", p.fallback > p.sent && "text-warn")}>
                        {p.fallback} <span className="text-muted-foreground text-xs">{pct(p.fallback, p.runs)}</span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{p.silent}</TableCell>
                      <TableCell className="text-right tabular-nums">{fmtMs(p.median_ms)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        <span className="text-ok">{p.good}</span> / <span className="text-bad">{p.bad}</span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="gap-2">
          <CardHeader>
            <CardTitle className="text-sm">{t("quality.activity.title")}</CardTitle>
            <CardDescription className="text-xs">{t("quality.activity.hint")}</CardDescription>
          </CardHeader>
          <CardContent>{q ? <ActivityHeatmap data={q.activity} /> : <Empty text={t("common.loading")} />}</CardContent>
        </Card>
      </div>
    </>
  );
}
