"""Start, stop and inspect the bot's systemd user service."""
from __future__ import annotations

import asyncio
from typing import Literal, Protocol

Action = Literal["start", "stop", "restart"]


class ServiceControl(Protocol):
    async def is_active(self) -> str: ...
    async def run(self, action: Action) -> None: ...
    async def journal(self, n: int = 50) -> list[str]: ...


async def _exec(*args: str) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(p.communicate(), timeout=30)
    return p.returncode or 0, out.decode(errors="replace")


class SystemdService:
    def __init__(self, unit: str = "botucha"):
        self.unit = unit

    async def is_active(self) -> str:
        try:
            _, out = await _exec("systemctl", "--user", "is-active", self.unit)
        except (OSError, asyncio.TimeoutError):
            return "unknown"
        state = out.strip().splitlines()[-1] if out.strip() else "unknown"
        return state if state in ("active", "inactive", "failed", "activating", "deactivating") else "unknown"

    async def run(self, action: Action) -> None:
        if action not in ("start", "stop", "restart"):
            raise ValueError(action)
        code, out = await _exec("systemctl", "--user", action, self.unit)
        if code:
            raise RuntimeError(out.strip() or f"systemctl {action} failed")

    async def journal(self, n: int = 50) -> list[str]:
        try:
            _, out = await _exec("journalctl", "--user", "-u", self.unit, "-n", str(int(n)), "--no-pager", "-o", "cat")
        except (OSError, asyncio.TimeoutError):
            return []
        return out.splitlines()
