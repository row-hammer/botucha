"""The Pipeline page: which path each reply took through generation and the filter, where the time went,
and the rates that matter (first-try pass, fallback, silent). Built from the trace tables only."""
from __future__ import annotations

import json
import re
from collections import Counter

from ..store import Store
from .metrics import RANGES, REPLIED, Range

STAGES = ("context", "retrieval", "prompt", "gen1", "proof", "gen2", "filter", "send")
_ATTEMPT = re.compile(r"(\d+)")


def _detail(raw: str | None) -> dict:
    try:
        d = json.loads(raw or "{}")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _attempt(name: str | None) -> int:
    m = _ATTEMPT.search(name or "")
    return int(m.group(1)) if m else 1


def reply_path(outcome: str | None, trigger: str, steps: list[tuple]) -> list[str]:
    """Nodes a reply passed through, e.g. trigger:direct -> a1:spelling -> a2:ok -> out:sent.
    steps are (kind, name, status, detail_json) in order. Each attempt ends in "ok", "error"
    (generation failed) or the first failed filter check ("rejected" if the trace has no checks)."""
    path = [f"trigger:{trigger or 'unknown'}"]
    results: dict[int, str] = {}
    proof: str | None = None  # Claude's proofreading between attempt 1 and 2, when it ran
    for kind, name, status, detail in steps:
        if kind == "proofread":
            proof = "error" if status == "error" else "ok"
        elif kind == "filter" and name == "proofread":
            proof = "ok" if status == "ok" else _first_failed(detail)
        elif kind == "generation" and status == "error":
            results[_attempt(name)] = "error"
        elif kind == "filter":
            results[_attempt(name)] = "ok" if status == "ok" else _first_failed(detail)
    for n in sorted(results):
        path.append(f"a{n}:{results[n]}")
        if n == 1 and proof:
            path.append(f"claude:{proof}")
    return path + [f"out:{outcome or 'unknown'}"]


def _first_failed(detail: str | None) -> str:
    checks = _detail(detail).get("checks", [])
    failed = [c.get("name") for c in checks if isinstance(c, dict) and not c.get("ok", True) and c.get("name")] \
        if isinstance(checks, list) else []
    return failed[0] if failed else "rejected"


def _reply_runs(store: Store, start: float) -> list[tuple]:
    """Finished reply traces since start: (id, started, outcome, trigger, steps)."""
    q = store.conn.execute
    traces = q("SELECT id, started, outcome, trigger FROM traces WHERE kind='reply' AND outcome IS NOT NULL "
               "AND started >= ? ORDER BY id", (start,)).fetchall()
    by_trace: dict[int, list[tuple]] = {t[0]: [] for t in traces}
    if by_trace:
        marks = ",".join("?" * len(by_trace))
        for tid, kind, name, status, dur, detail in q(
                f"SELECT trace_id, kind, name, status, duration_ms, detail FROM trace_steps "
                f"WHERE trace_id IN ({marks}) ORDER BY trace_id, seq", list(by_trace)):
            by_trace[tid].append((kind, name, status, detail, dur))
    return [(tid, started, outcome, trigger, by_trace[tid]) for tid, started, outcome, trigger in traces]


def _start(now: float, range_: Range) -> tuple[float, int, int]:
    size, count = RANGES[range_]
    return (now // size) * size - (count - 1) * size, size, count


def _stage_ms(steps: list[tuple]) -> dict[str, float]:
    out = dict.fromkeys(STAGES, 0.0)
    for kind, name, _status, _detail, dur in steps:
        key = (("gen1" if _attempt(name) == 1 else "gen2") if kind == "generation"
               else "proof" if kind == "proofread" else kind if kind in out else None)
        if key:
            out[key] += dur or 0.0
    return out


def compute_pipeline(store: Store, now: float, range_: Range) -> dict:
    start, size, count = _start(now, range_)
    runs = _reply_runs(store, start)
    nodes: Counter[str] = Counter()
    links: Counter[tuple[str, str]] = Counter()
    attempts: list[int] = []
    first_try = 0
    sums = [dict.fromkeys(STAGES, 0.0) for _ in range(count)]
    counts = [0] * count
    for _tid, started, outcome, trigger, steps in runs:
        path = reply_path(outcome, trigger, [s[:4] for s in steps])
        nodes.update(path)
        links.update(zip(path, path[1:]))
        attempts.append(sum(1 for p in path if p.startswith("a")))
        first_try += "a1:ok" in path
        if outcome in REPLIED:
            b = min(count - 1, max(0, int((started - start) // size)))
            counts[b] += 1
            for k, v in _stage_ms(steps).items():
                sums[b][k] += v
    outcomes = Counter(o for _, _, o, _, _ in runs)
    stages = [{"t": start + i * size, "n": counts[i],
               **{k: (round(sums[i][k] / counts[i], 1) if counts[i] else None) for k in STAGES}}
              for i in range(count)]
    return {
        "rates": {"runs": len(runs), "sent": outcomes["sent"], "fallback": outcomes["fallback"],
                  "silent": len(runs) - outcomes["sent"] - outcomes["fallback"], "first_try": first_try,
                  "avg_attempts": round(sum(attempts) / len(attempts), 2) if attempts else None},
        "nodes": [{"id": k, "n": v} for k, v in nodes.items()],
        "links": [{"source": a, "target": b, "value": v} for (a, b), v in links.items()],
        "stages": stages,
    }


def traces_on_path(store: Store, node: str, now: float, range_: Range) -> list[int]:
    """Ids (newest first) of finished replies in range whose path passes through node."""
    start, _, _ = _start(now, range_)
    return [tid for tid, _, outcome, trigger, steps in reversed(_reply_runs(store, start))
            if node in reply_path(outcome, trigger, [s[:4] for s in steps])]
