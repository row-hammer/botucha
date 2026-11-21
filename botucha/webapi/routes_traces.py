"""Trace list and detail, metrics, and the live event stream."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..store import Store
from .metrics import Range, compute_metrics
from .pipeline import compute_pipeline, traces_on_path
from .quality import compute_quality
from .routes_status import status_body

router = APIRouter()

_COLS = "id, kind, chat_id, msg_id, user_name, trigger, outcome, error, reply, started, duration_ms"
_ATTEMPTS = "(SELECT COUNT(*) FROM trace_steps s WHERE s.trace_id=traces.id AND s.kind='generation')"


def _summary(r: tuple) -> dict:
    keys = _COLS.split(", ") + ["attempts"]
    return dict(zip(keys, r))


def list_traces(store: Store, *, kind: str | None = None, outcome: str | None = None,
                before_id: int | None = None, after_id: int | None = None, limit: int = 50) -> list[dict]:
    where, args = [], []
    for col, val in (("kind", kind), ("outcome", outcome)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    if before_id is not None:
        where.append("id<?")
        args.append(before_id)
    if after_id is not None:
        where.append("id>?")
        args.append(after_id)
    sql = f"SELECT {_COLS}, {_ATTEMPTS} FROM traces"
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = "ASC" if after_id is not None else "DESC"
    rows = store.conn.execute(f"{sql} ORDER BY id {order} LIMIT ?", (*args, limit)).fetchall()
    return [_summary(r) for r in rows]


@router.get("/api/traces")
async def traces(request: Request, kind: str | None = None, outcome: str | None = None,
                 before_id: int | None = None, limit: int = Query(50, ge=1, le=200),
                 path: str | None = None, range: Range = "30d") -> list[dict]:  # noqa: A002
    deps = request.app.state.deps
    if path:  # drill-down from the Pipeline page: replies that passed through one node
        ids = traces_on_path(deps.store, path, deps.clock(), range)
        if before_id is not None:
            ids = [i for i in ids if i < before_id]
        ids = ids[:limit]
        if not ids:
            return []
        rows = deps.store.conn.execute(f"SELECT {_COLS}, {_ATTEMPTS} FROM traces WHERE id IN "
                                       f"({','.join('?' * len(ids))}) ORDER BY id DESC", ids).fetchall()
        return [_summary(r) for r in rows]
    return list_traces(deps.store, kind=kind, outcome=outcome, before_id=before_id, limit=limit)


@router.get("/api/traces/by-message")
async def by_message(request: Request, chat_id: int, msg_id: int) -> dict:
    r = request.app.state.deps.store.conn.execute(
        "SELECT trace_id FROM trace_messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)).fetchone()
    return {"trace_id": r[0] if r else None}


@router.get("/api/traces/{trace_id}")
async def trace(request: Request, trace_id: int) -> dict:
    store = request.app.state.deps.store
    r = store.conn.execute(f"SELECT {_COLS}, {_ATTEMPTS} FROM traces WHERE id=?", (trace_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such trace")
    rows = store.conn.execute("SELECT id, seq, kind, name, status, started, duration_ms, detail, prompt IS NOT NULL "
                              "FROM trace_steps WHERE trace_id=? ORDER BY seq", (trace_id,)).fetchall()
    steps = [{"id": i, "seq": seq, "kind": k, "name": n, "status": st, "started": s, "duration_ms": d,
              "detail": json.loads(det or "{}"), "has_prompt": bool(hp)}
             for i, seq, k, n, st, s, d, det, hp in rows]
    return {"trace": _summary(r), "steps": steps}


@router.get("/api/traces/{trace_id}/prompt")
async def trace_prompt(request: Request, trace_id: int) -> dict:
    r = request.app.state.deps.store.conn.execute(
        "SELECT prompt FROM trace_steps WHERE trace_id=? AND prompt IS NOT NULL ORDER BY seq LIMIT 1",
        (trace_id,)).fetchone()
    return {"prompt": r[0] if r else None}


@router.get("/api/metrics")
async def metrics(request: Request, range: Range = "24h") -> dict:  # noqa: A002  (query parameter name)
    deps = request.app.state.deps
    return compute_metrics(deps.store, deps.clock(), range)


@router.get("/api/pipeline")
async def pipeline(request: Request, range: Range = "24h") -> dict:  # noqa: A002  (query parameter name)
    deps = request.app.state.deps
    return compute_pipeline(deps.store, deps.clock(), range)


@router.get("/api/quality")
async def quality(request: Request, range: Range = "7d") -> dict:  # noqa: A002  (query parameter name)
    deps = request.app.state.deps
    return compute_quality(deps.store, deps.clock(), range, num_ctx=deps.cfg.model.num_ctx)


def _event(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


STUCK_S = 600.0  # a trace unfinished for this long was cut short (bot restarted mid-reply)


async def live_events(store: Store, status: Callable[[], Awaitable[dict]], *, poll_s: float = 1.0,
                      status_every_s: float = 5.0, clock: Callable[[], float] = time.time) -> AsyncIterator[str]:
    """Status first, then every trace as it finishes, and status again every status_every_s.
    Traces can finish out of order (a reply during a learning run), so the cursor only moves past
    traces that are finished or stuck."""
    # start after the newest finished trace, but before any that are still running (they are emitted when done)
    floor = store.conn.execute("SELECT COALESCE(MAX(id), 0) FROM traces WHERE outcome IS NOT NULL").fetchone()[0]
    running = store.conn.execute("SELECT MIN(id) FROM traces WHERE outcome IS NULL AND started >= ?",
                                 (clock() - STUCK_S,)).fetchone()[0]
    if running is not None:
        floor = min(floor, running - 1)
    emitted: set[int] = set()
    progress: dict[int, int] = {}  # running trace id -> steps already reported
    yield _event("status", await status())
    sent_status = time.monotonic()
    while True:
        rows = list_traces(store, after_id=floor, limit=200)
        pending = []
        for t in rows:
            if t["outcome"]:
                if t["id"] not in emitted:
                    emitted.add(t["id"])
                    yield _event("trace", t)
            elif t["started"] >= clock() - STUCK_S:
                pending.append(t["id"])
        for ev in _progress(store, [t for t in rows if t["id"] in pending], progress):
            yield ev
        if rows:
            floor = min(pending) - 1 if pending else rows[-1]["id"]
            emitted = {i for i in emitted if i > floor}
        if time.monotonic() - sent_status >= status_every_s:
            yield _event("status", await status())
            sent_status = time.monotonic()
        await asyncio.sleep(poll_s)


def _progress(store: Store, running: list[dict], seen: dict[int, int]) -> list[str]:
    """A progress event for each running trace that wrote a new step since the last poll."""
    out = []
    for t in running:
        n, last = store.conn.execute(
            "SELECT COUNT(*), (SELECT kind || char(31) || COALESCE(name, '') || char(31) || status FROM trace_steps "
            "WHERE trace_id=? ORDER BY seq DESC LIMIT 1) FROM trace_steps WHERE trace_id=?",
            (t["id"], t["id"])).fetchone()
        if n and seen.get(t["id"]) != n:
            seen[t["id"]] = n
            kind, name, status = last.split("\x1f")
            out.append(_event("progress", {"id": t["id"], "kind": t["kind"], "user_name": t["user_name"],
                                           "trigger": t["trigger"], "started": t["started"], "steps": n,
                                           "last": {"kind": kind, "name": name or None, "status": status}}))
    for tid in [i for i in seen if i not in {t["id"] for t in running}]:
        del seen[tid]
    return out


@router.get("/api/live")
async def live(request: Request) -> StreamingResponse:
    async def stream():
        async for ev in live_events(request.app.state.deps.store, lambda: status_body(request)):
            if await request.is_disconnected():
                break
            yield ev
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
