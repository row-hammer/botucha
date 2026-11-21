"""Step traces of replies and learning runs, for the web dashboard. Tracing never breaks the bot:
every database write is best-effort and only logs a warning when it fails."""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from .store import Store

log = logging.getLogger(__name__)

DAY_S = 86_400.0


@dataclass
class StepHandle:
    status: str = "ok"
    detail: dict = field(default_factory=dict)
    prompt: str | None = None


def _dump(detail: dict | None) -> str:
    return json.dumps(detail or {}, ensure_ascii=False, default=str)


class TraceRun:
    def __init__(self, store: Store | None, trace_id: int | None, *, clock: Callable[[], float],
                 perf: Callable[[], float], t0: float):
        self.store, self.id, self.clock, self.perf, self._t0 = store, trace_id, clock, perf, t0
        self._seq = 0
        self._started = clock()

    def _write(self, sql: str, args: tuple) -> None:
        if self.store is None or self.id is None:
            return
        try:
            self.store.conn.execute(sql, args)
            self.store.conn.commit()
        except Exception as e:
            log.warning("trace write failed: %s", e)

    def add_step(self, kind: str, *, name: str | None = None, status: str = "ok", duration_ms: float = 0.0,
                 detail: dict | None = None, prompt: str | None = None, started: float | None = None) -> None:
        seq, self._seq = self._seq, self._seq + 1
        self._write("INSERT INTO trace_steps (trace_id, seq, kind, name, status, started, duration_ms, detail, prompt) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (self.id, seq, kind, name, status, self.clock() if started is None else started,
                     duration_ms, _dump(detail), prompt))

    @contextmanager
    def step(self, kind: str, name: str | None = None) -> Iterator[StepHandle]:
        h, started, t = StepHandle(), self.clock(), self.perf()
        try:
            yield h
        except BaseException as e:
            h.status = "error"
            h.detail["error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            self.add_step(kind, name=name, status=h.status, duration_ms=(self.perf() - t) * 1000,
                          detail=h.detail, prompt=h.prompt, started=started)

    def finish(self, outcome: str, *, reply: str | None = None, error: str | None = None,
               sent: Iterable[tuple[int, int]] = ()) -> None:
        self._write("UPDATE traces SET outcome=?, reply=?, error=?, duration_ms=? WHERE id=?",
                    (outcome, reply, error, (self.perf() - self._t0) * 1000, self.id))
        for chat_id, msg_id in sent:
            self._write("INSERT OR REPLACE INTO trace_messages (trace_id, chat_id, msg_id) VALUES (?,?,?)",
                        (self.id, chat_id, msg_id))


NULL_RUN = TraceRun(None, None, clock=lambda: 0.0, perf=lambda: 0.0, t0=0.0)


class Tracer:
    def __init__(self, store: Store, *, clock: Callable[[], float] = time.time,
                 perf: Callable[[], float] = time.perf_counter):
        self.store, self.clock, self.perf = store, clock, perf

    def start(self, kind: str, *, chat_id: int | None = None, msg_id: int | None = None,
              user_name: str | None = None, trigger: str = "") -> TraceRun:
        t0 = self.perf()
        try:
            tid = self.store.conn.execute(
                "INSERT INTO traces (kind, chat_id, msg_id, user_name, trigger, started) VALUES (?,?,?,?,?,?)",
                (kind, chat_id, msg_id, user_name, trigger, self.clock())).lastrowid
            self.store.conn.commit()
        except Exception as e:
            log.warning("trace start failed: %s", e)
            tid = None
        return TraceRun(self.store, tid, clock=self.clock, perf=self.perf, t0=t0)


def prune_traces(store: Store, now: float, *, keep_days: int = 30, prompt_days: int = 7) -> int:
    """Drop traces older than keep_days and full prompts older than prompt_days. Returns traces deleted."""
    c = store.conn
    c.execute("UPDATE trace_steps SET prompt=NULL WHERE prompt IS NOT NULL AND trace_id IN "
              "(SELECT id FROM traces WHERE started < ?)", (now - prompt_days * DAY_S,))
    old = "(SELECT id FROM traces WHERE started < ?)"
    cutoff = (now - keep_days * DAY_S,)
    c.execute(f"DELETE FROM trace_steps WHERE trace_id IN {old}", cutoff)
    c.execute(f"DELETE FROM trace_messages WHERE trace_id IN {old}", cutoff)
    n = c.execute("DELETE FROM traces WHERE started < ?", cutoff).rowcount
    c.commit()
    return n
