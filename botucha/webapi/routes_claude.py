"""Claude proofreading: status, the on/off switch, and approving words as known."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..proofread import ClaudeProofreader, set_known_word

router = APIRouter()


class SwitchIn(BaseModel):
    on: bool


class KnownWordIn(BaseModel):
    word: str = Field(min_length=1, max_length=40, pattern=r"^[^\W\d_]+$")
    known: bool


def claude_status(request: Request) -> dict:
    deps = request.app.state.deps
    # the dashboard never holds the key: it only knows whether the bot has one
    p = ClaudeProofreader(deps.cfg.claude, deps.store, api_key="set" if deps.claude_key else None,
                          client=object() if deps.claude_key else None, clock=deps.clock)
    return p.status()


@router.get("/api/claude")
async def status(request: Request) -> dict:
    return claude_status(request)


@router.post("/api/control/claude")
async def switch(request: Request, body: SwitchIn) -> dict:
    request.app.state.deps.store.set_state("claude_on", "1" if body.on else "0")
    return claude_status(request)


@router.post("/api/known-words")
async def known_word(request: Request, body: KnownWordIn) -> dict:
    deps = request.app.state.deps
    set_known_word(deps.store, body.word, body.known, now=deps.clock())
    return {"ok": True}
