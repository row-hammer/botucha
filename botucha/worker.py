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
        self._current: list[Job] = []  # the batch being answered right now
        self._first_at = 0.0
        self._last_activity = 0.0
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._running = False
        self._stopped = False
        self._draining = False

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()

    @property
    def pending(self) -> bool:
        return bool(self._queue) or self._running

    def submit(self, job: Job) -> None:
        if self._draining or self._stopped:
            log.info("shutting down: reply to %d/%d not taken", job.chat_id, job.msg_id)
            return
        now = self._now()
        if not self._queue:
            self._first_at = now
        self._queue.append(job)
        self._last_activity = now
        self._idle.clear()
        self._wake.set()

    def activity(self) -> None:
        self._last_activity = self._now()

    async def run(self) -> None:
        while not self._stopped:
            await self._wake.wait()
            self._wake.clear()
            while self._queue and not self._stopped:
                deadline = min(self._last_activity + self.quiet_s, self._first_at + self.max_wait_s)
                delay = 0 if self._draining else deadline - self._now()
                if delay > 0:
                    try:  # a drain cuts the burst wait short
                        await asyncio.wait_for(self._wake.wait(), delay)
                        self._wake.clear()
                    except TimeoutError:
                        pass
                    continue
                jobs, self._queue = self._queue, []
                self._current, self._running = jobs, True
                try:
                    await self.run_job(jobs)
                except Exception:
                    log.exception("reply job failed")
                finally:
                    self._current, self._running = [], False
            if not self._queue and not self._running:
                self._idle.set()

    async def drain(self, timeout_s: float) -> list[Job]:
        """Stop taking jobs, answer what is running and queued without waiting for the burst to end, for up
        to timeout_s. Returns the jobs that got no reply in time (the running batch first)."""
        self._draining = True
        self._wake.set()
        if self.pending:
            try:
                await asyncio.wait_for(self._idle.wait(), timeout_s)
            except TimeoutError:
                pass
        left = [*self._current, *self._queue]
        self._stopped = True
        self._wake.set()
        return left

    async def stop(self) -> None:
        self._stopped = True
        self._wake.set()
