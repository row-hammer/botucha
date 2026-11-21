"use client";

import { useLocale, useT } from "@/lib/i18n";

/** Messages per weekday (rows, Monday first) and hour (columns), darker = busier. */
export function ActivityHeatmap({ data }: { data: number[][] }) {
  const t = useT();
  const locale = useLocale();
  const max = Math.max(1, ...data.flat());
  // 2026-11-16 is a Monday: label rows in the viewer's language
  const day = (i: number) => new Date(2026, 10, 16 + i).toLocaleDateString(locale, { weekday: "short" });
  return (
    <div className="overflow-x-auto">
      <div
        className="grid min-w-[560px] gap-[3px] text-[10px] text-muted-foreground"
        style={{ gridTemplateColumns: "2.5rem repeat(24, minmax(0, 1fr))" }}
      >
        <span />
        {Array.from({ length: 24 }, (_, h) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed 24 hour columns
          <span key={h} className="text-center tabular-nums">
            {h % 3 === 0 ? h : ""}
          </span>
        ))}
        {data.map((row, d) => (
          <div key={day(d)} className="contents">
            <span className="self-center pr-1 text-right">{day(d)}</span>
            {row.map((n, h) => (
              <span
                // biome-ignore lint/suspicious/noArrayIndexKey: fixed 24 hour columns
                key={h}
                title={t("quality.activity.cell", { day: day(d), h, n })}
                className="aspect-square rounded-[3px]"
                style={{
                  background: n
                    ? `color-mix(in oklch, var(--chart-1) ${Math.round(15 + (n / max) * 85)}%, transparent)`
                    : "var(--muted)",
                }}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
