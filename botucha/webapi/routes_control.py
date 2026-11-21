"""On/off, frequency, quiet time (through the state table the bot polls) and the systemd service."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .routes_status import status_body

router = APIRouter()


class StateIn(BaseModel):
    enabled: bool | None = None
    random_n: int | None = Field(None, ge=2, le=10_000)
    quiet_min: int | None = Field(None, ge=0, le=7 * 24 * 60)


class ServiceIn(BaseModel):
    action: Literal["start", "stop", "restart"]


@router.post("/api/control/state")
async def set_state(request: Request, body: StateIn) -> dict:
    deps = request.app.state.deps
    if body.enabled is not None:
        deps.store.set_state("enabled", "1" if body.enabled else "0")
    if body.random_n is not None:
        deps.store.set_state("random_n", str(body.random_n))
    if body.quiet_min is not None:
        deps.store.set_state("quiet_until", str(deps.clock() + 60 * body.quiet_min) if body.quiet_min else "0")
    return await status_body(request)


@router.post("/api/control/service")
async def service(request: Request, body: ServiceIn) -> dict:
    try:
        await request.app.state.deps.service.run(body.action)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    return {"ok": True}


@router.get("/api/control/journal")
async def journal(request: Request, n: int = Query(50, ge=1, le=500)) -> dict:
    return {"lines": await request.app.state.deps.service.journal(n)}
