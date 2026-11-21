export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "–";
  return ms >= 1000 ? `${(ms / 1000).toFixed(ms >= 10_000 ? 0 : 1)} s` : `${Math.round(ms)} ms`;
}

export function fmtTime(ts: number, locale: string, withDate = true): string {
  return new Date(ts * 1000).toLocaleString(locale, {
    ...(withDate ? { month: "short", day: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtNum(n: number | null | undefined, digits = 1): string {
  return n == null ? "–" : Number.isInteger(n) ? String(n) : n.toFixed(digits);
}
