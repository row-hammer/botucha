"""Performance numbers for the Overview page, computed from traces and feedback."""
from __future__ import annotations

import json
import math
from typing import Literal

from ..store import Store

Range = Literal["24h", "7d", "30d"]
RANGES: dict[str, tuple[int, int]] = {"24h": (3600, 24), "7d": (86_400, 7), "30d": (86_400, 30)}
REPLIED = ("sent", "fallback")


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    s = sorted(values)
    return s[max(1, math.ceil(p / 100 * len(s))) - 1]


def compute_metrics(store: Store, now: float, range_: Range) -> dict:
    size, count = RANGES[range_]
    start = (now // size) * size - (count - 1) * size
    q = store.conn.execute
    traces = q("SELECT id, started, duration_ms, outcome FROM traces WHERE kind='reply' AND started >= ?",
               (start,)).fetchall()
    ids = [t[0] for t in traces]
    marks = ",".join("?" * len(ids)) or "NULL"
    steps = q(f"SELECT trace_id, kind, detail FROM trace_steps WHERE trace_id IN ({marks}) "
              "AND kind IN ('generation', 'filter')", ids).fetchall()
    started_of = {t[0]: t[1] for t in traces}

    def bucket(ts: float) -> int:
        return min(count - 1, max(0, int((ts - start) // size)))

    durations: list[list[float]] = [[] for _ in range(count)]
    for _, started, dur, outcome in traces:
        if outcome in REPLIED and dur is not None:
            durations[bucket(started)].append(dur)
    toks: list[list[float]] = [[] for _ in range(count)]
    rejections: dict[str, int] = {}
    for tid, kind, detail in steps:
        d = json.loads(detail or "{}")
        if kind == "generation" and d.get("tok_s"):
            toks[bucket(started_of[tid])].append(float(d["tok_s"]))
        elif kind == "filter":
            for c in d.get("checks", []):
                if not c.get("ok", True):
                    rejections[c["name"]] = rejections.get(c["name"], 0) + 1
    ratings = [{"t": start + i * size, "good": 0, "bad": 0} for i in range(count)]
    for score, ts in q("SELECT score, ts FROM feedback WHERE ts >= ?", (start,)):
        ratings[bucket(ts)]["good" if score > 0 else "bad"] += 1
    all_durations = [d for b in durations for d in b]
    all_toks = [t for b in toks for t in b]
    series = [{"t": start + i * size, "replies": len(durations[i]), "p50_ms": percentile(durations[i], 50),
               "p95_ms": percentile(durations[i], 95),
               "tok_s": round(sum(toks[i]) / len(toks[i]), 2) if toks[i] else None} for i in range(count)]
    return {
        "cards": {"replies": len(all_durations), "median_ms": percentile(all_durations, 50),
                  "tok_s": round(sum(all_toks) / len(all_toks), 2) if all_toks else None,
                  "rejections": sum(rejections.values()),
                  "good": sum(r["good"] for r in ratings), "bad": sum(r["bad"] for r in ratings)},
        "series": series,
        "rejections_by_filter": rejections,
        "ratings": ratings,
    }
