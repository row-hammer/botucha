"use client";

import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtMs } from "@/lib/format";
import { useT } from "@/lib/i18n";
import type { Pipeline, StageKey } from "@/lib/types";

export const STAGE_COLORS: Record<StageKey, string> = {
  context: "var(--chart-5)",
  retrieval: "var(--chart-3)",
  prompt: "var(--muted-foreground)",
  gen1: "var(--chart-1)",
  gen2: "var(--chart-4)",
  filter: "var(--chart-2)",
  send: "var(--ok)",
};
const KEYS = Object.keys(STAGE_COLORS) as StageKey[];
const axis = { stroke: "var(--muted-foreground)", fontSize: 12, tickLine: false, axisLine: false };

/** Mean time per stage for each hour/day; the stack height is the mean reply time. */
export function StageChart({ data, tick }: { data: Pipeline["stages"]; tick: (ts: number) => string }) {
  const t = useT();
  const rows = data.map((s) => ({ ...s, label: tick(s.t) }));
  return (
    <ResponsiveContainer>
      <BarChart data={rows}>
        <CartesianGrid stroke="var(--border)" vertical={false} />
        <XAxis dataKey="label" {...axis} minTickGap={24} />
        <YAxis {...axis} tickFormatter={(v) => fmtMs(v)} width={56} />
        <Tooltip
          cursor={{ fill: "var(--muted)" }}
          contentStyle={{
            background: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
          }}
          formatter={(v) => fmtMs(v as number)}
          labelFormatter={(l, p) => (p?.[0] ? `${l} · ${t("pipeline.replies", { n: p[0].payload.n })}` : String(l))}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        {KEYS.map((k, i) => (
          <Bar
            key={k}
            isAnimationActive={false}
            dataKey={k}
            stackId="s"
            name={t(`pipeline.stage.${k}`)}
            fill={STAGE_COLORS[k]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** One 100% bar: share of total reply time per stage over the whole range. */
export function StageShare({ data }: { data: Pipeline["stages"] }) {
  const t = useT();
  const totals = KEYS.map((k) => ({ k, ms: data.reduce((sum, s) => sum + (s[k] ?? 0) * s.n, 0) }));
  const n = data.reduce((sum, s) => sum + s.n, 0);
  const all = totals.reduce((sum, x) => sum + x.ms, 0);
  if (!all || !n) return null;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex h-3 overflow-hidden bg-muted">
        {totals.map(({ k, ms }) =>
          ms > 0 ? (
            <div
              key={k}
              style={{ width: `${(ms / all) * 100}%`, background: STAGE_COLORS[k] }}
              title={t(`pipeline.stage.${k}`)}
            />
          ) : null,
        )}
      </div>
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-2 lg:grid-cols-1">
        {totals.map(({ k, ms }) => (
          <div key={k} className="flex items-center gap-1.5">
            <span className="size-2 shrink-0" style={{ background: STAGE_COLORS[k] }} />
            <dt className="truncate text-muted-foreground">{t(`pipeline.stage.${k}`)}</dt>
            <dd className="ml-auto font-medium tabular-nums">
              {fmtMs(ms / n)} <span className="text-muted-foreground">{Math.round((ms / all) * 100)}%</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
