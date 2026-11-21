"""Single reply worker: waits for a burst of messages to end, then answers it in one go."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class Job:
    chat_id: int
    msg_id: int
    direct: bool
    serious: bool
    recall: bool
    trigger: str = ""


class ReplyWorker:
    def __init__(self, run_job: Callable[[list[Job]], Awaitable[None]], *, quiet_s: float, max_wait_s: float):
        self.run_job = run_job
        self.quiet_s = quiet_s
        self.max_wait_s = max_wait_s
        self._queue: list[Job] = []
        self._first_at = 0.0
        self._last_activity = 0.0
        self._wake = asyncio.Event()
        self._running = False
        self._stopped = False

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()

    @property
    def pending(self) -> bool:
        return bool(self._queue) or self._running

    def submit(self, job: Job) -> None:
        now = self._now()
        if not self._queue:
            self._first_at = now
        self._queue.append(job)
        self._last_activity = now
        self._wake.set()

    def activity(self) -> None:
        self._last_activity = self._now()

    async def run(self) -> None:
        while not self._stopped:
            await self._wake.wait()
            self._wake.clear()
            while self._queue:
                deadline = min(self._last_activity + self.quiet_s, self._first_at + self.max_wait_s)
                delay = deadline - self._now()
                if delay > 0:
                    await asyncio.sleep(delay)
                    continue
                jobs, self._queue = self._queue, []
                self._running = True
                try:
                    await self.run_job(jobs)
                except Exception:
                    log.exception("reply job failed")
                finally:
                    self._running = False

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
