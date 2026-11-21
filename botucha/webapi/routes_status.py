"""Session token and bot status."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


async def status_body(request: Request) -> dict:
    deps = request.app.state.deps
    g = deps.store.get_state
    started = g("bot_started_at")
    return {
        "bot": await deps.service.is_active(),
        "model": deps.cfg.model.chat_model,
        "started_at": float(started) if started else None,
        "last_error": g("last_error") or None,
        "enabled": g("enabled", "1") == "1",
        "random_n": int(g("random_n", str(deps.cfg.trigger.random_n))),
        "quiet_until": float(g("quiet_until", "0") or 0),
    }


@router.get("/api/session")
async def session(request: Request) -> dict:
    return {"token": request.app.state.token}


@router.get("/api/status")
async def status(request: Request) -> dict:
    return await status_body(request)
