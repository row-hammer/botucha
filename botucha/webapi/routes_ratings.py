"""Ratings and corrections: review them and export them for later fine-tuning."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()


class ReviewIn(BaseModel):
    kind: Literal["feedback", "correction"]
    chat_id: int
    msg_id: int
    user_id: int
    reviewed: bool


def _trace_id(store, chat_id: int, msg_id: int) -> int | None:
    r = store.conn.execute("SELECT trace_id FROM trace_messages WHERE chat_id=? AND msg_id=?",
                           (chat_id, msg_id)).fetchone()
    return r[0] if r else None


@router.get("/api/ratings")
async def ratings(request: Request) -> list[dict]:
    store = request.app.state.deps.store
    rows = store.ratings()
    for r in rows:
        r["trace_id"] = _trace_id(store, r["chat_id"], r["msg_id"])
    return rows


@router.post("/api/ratings/review")
async def review(request: Request, body: ReviewIn) -> dict:
    if not request.app.state.deps.store.set_reviewed(body.kind, body.chat_id, body.msg_id, body.user_id, body.reviewed):
        raise HTTPException(404, "no such rating")
    return {"ok": True}


def _history(store, chat_id: int, msg_id: int, n: int = 20) -> list[str]:
    row = store.conn.execute("SELECT rowid FROM messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)).fetchone()
    if not row:
        return []
    rows = store.conn.execute("SELECT name, text FROM messages WHERE chat_id=? AND rowid<? AND text != '' "
                              "AND text NOT LIKE '/%' ORDER BY rowid DESC LIMIT ?", (chat_id, row[0], n)).fetchall()
    return [f"{name}: {text}" for name, text in reversed(rows)]


@router.get("/api/ratings/export")
async def export(request: Request) -> Response:
    store = request.app.state.deps.store
    lines = []
    for r in store.ratings(limit=100_000):
        item = {"history": _history(store, r["chat_id"], r["msg_id"]), "reply": r["original"]}
        if r["kind"] == "feedback":
            item.update(score=r["score"], reason=r["reason"])
        else:
            item["correction"] = r["text"]
        lines.append(json.dumps(item, ensure_ascii=False))
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="application/x-ndjson",
                    headers={"Content-Disposition": 'attachment; filename="botucha-ratings.jsonl"'})
