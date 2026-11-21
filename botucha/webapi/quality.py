"""The Quality page: which words the spell check flags, how many attempts replies need, who triggers
them and how that goes, how full the context window gets, and when the group is active."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from statistics import mean

from ..proofread import known_words
from ..store import Store
from ..trigger import fold
from .metrics import REPLIED, Range, percentile
from .pipeline import _detail, _reply_runs, _start

TOP_WORDS = 40


def _trigger_kinds(trigger: str) -> list[str]:
    kinds = [part.split(":", 1)[0] for part in (trigger or "").split("+") if part]
    return kinds or ["unknown"]


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _flagged(detail: dict) -> list[str]:
    checks = detail.get("checks")
    if not isinstance(checks, list):
        return []
    for c in checks:
        if isinstance(c, dict) and c.get("name") == "spelling" and not c.get("ok", True):
            return [w.strip() for w in str(c.get("reason") or "").split(",") if w.strip()]
    return []


def compute_quality(store: Store, now: float, range_: Range, *, num_ctx: int,
                    tz: dt.tzinfo | None = None) -> dict:
    start, _, _ = _start(now, range_)
    runs = _reply_runs(store, start)

    words: Counter[str] = Counter()
    word_traces: dict[str, set[int]] = {}
    word_last: dict[str, tuple[float, int]] = {}
    attempts: Counter[str] = Counter()
    triggers: Counter[str] = Counter()
    prompt_tokens: list[float] = []
    facts: list[int] = []
    chunks: list[int] = []
    history: list[int] = []
    people: dict[str, dict] = {}
    durations: dict[str, list[float]] = {}
    trace_person: dict[int, str] = {}
    meta = {tid: (who, ms) for tid, who, ms in store.conn.execute(
        "SELECT id, user_name, duration_ms FROM traces WHERE kind='reply' AND started >= ?", (start,))}

    for tid, started, outcome, trigger, steps in runs:
        triggers.update(_trigger_kinds(trigger))
        gens = 0
        for kind, name, _status, raw, _dur in steps:
            d = _detail(raw)
            if kind == "filter":
                for w in _flagged(d):
                    key = w.lower()
                    words[key] += 1
                    word_traces.setdefault(key, set()).add(tid)
                    if started >= word_last.get(key, (-1.0, 0))[0]:
                        word_last[key] = (started, tid)
            elif kind == "generation":
                gens += 1
                if gens == 1 and (n := _num(d.get("prompt_eval_count"))) is not None:
                    prompt_tokens.append(n)
            elif kind == "retrieval":
                facts.append(len(d.get("facts") or []))
                chunks.append(len(d.get("chunks") or []))
            elif kind == "context" and (h := _num(d.get("history"))) is not None:
                history.append(int(h))
        if gens:
            attempts[str(gens)] += 1
        name, ms = meta.get(tid, (None, None))
        name = name or "–"
        person = people.setdefault(name, {
            "name": name, "runs": 0, "sent": 0, "fallback": 0, "silent": 0, "median_ms": None, "good": 0, "bad": 0})
        trace_person[tid] = name
        person["runs"] += 1
        if outcome in ("sent", "fallback"):
            person[outcome] += 1
        else:
            person["silent"] += 1
        if outcome in REPLIED and ms is not None:
            durations.setdefault(name, []).append(ms)

    for name, ds in durations.items():
        people[name]["median_ms"] = percentile(ds, 50)
    if trace_person:
        marks = ",".join("?" * len(trace_person))
        for tid, score in store.conn.execute(
                f"SELECT tm.trace_id, f.score FROM feedback f JOIN trace_messages tm "
                f"ON tm.chat_id=f.chat_id AND tm.msg_id=f.msg_id WHERE tm.trace_id IN ({marks})",
                list(trace_person)):
            people[trace_person[tid]]["good" if score > 0 else "bad"] += 1

    activity = [[0] * 24 for _ in range(7)]
    for (ts,) in store.conn.execute("SELECT ts FROM messages WHERE is_bot=0 AND ts >= ? AND ts <= ?", (start, now)):
        t = dt.datetime.fromtimestamp(ts, tz)
        activity[t.weekday()][t.hour] += 1

    top = words.most_common(TOP_WORDS)
    claude = _latest_verdicts(store, [w for w, _ in top])
    known = known_words(store)
    return {
        "words": [{"word": w, "n": n, "traces": len(word_traces[w]), "last": word_last[w][0],
                   "trace_id": word_last[w][1], "claude": claude.get(w), "known": fold(w) in known}
                  for w, n in top],
        "attempts": dict(sorted(attempts.items())),
        "triggers": dict(triggers.most_common()),
        "people": sorted(people.values(), key=lambda p: (-p["runs"], p["name"])),
        "context": {"limit": num_ctx, "p50": percentile(prompt_tokens, 50), "p95": percentile(prompt_tokens, 95),
                    "max": max(prompt_tokens) if prompt_tokens else None, "replies": len(prompt_tokens),
                    "facts": round(mean(facts), 1) if facts else None,
                    "chunks": round(mean(chunks), 1) if chunks else None,
                    "history": round(mean(history), 1) if history else None},
        "activity": activity,
    }



def _latest_verdicts(store: Store, words: list[str]) -> dict[str, dict]:
    """Claude's most recent verdict per word (lower-case), when it judged that word."""
    if not words:
        return {}
    out: dict[str, dict] = {}
    marks = ",".join("?" * len(words))
    for word, verdict, fix in store.conn.execute(
            f"SELECT lower(word), verdict, fix FROM spell_fixes WHERE lower(word) IN ({marks}) ORDER BY id", words):
        out[word] = {"verdict": verdict, "fix": fix}
    return out
