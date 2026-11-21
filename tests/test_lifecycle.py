"""Startup and shutdown of the real process: drain, save what is left, and fail loudly when a loop dies."""
import asyncio

from botucha.__main__ import DRAIN_S, shutdown, watch
from botucha.app import ReplyJob
from botucha.store import StoredMessage
from tests.fakes import FakeLLM
from tests.test_app import C, app, inc  # noqa: F401  (app is a fixture)


def test_drain_fits_inside_systemds_stop_timeout():
    from pathlib import Path
    unit = (Path(__file__).parent.parent / "deploy" / "botucha.service").read_text()
    stop = next(int(l.split("=")[1].rstrip("s")) for l in unit.splitlines() if l.startswith("TimeoutStopSec="))
    assert DRAIN_S + 10 <= stop


async def test_shutdown_finishes_a_reply_that_is_generating(app):
    bot, store, _, out = await app()

    class Slow(FakeLLM):
        async def chat_ex(self, *a, **k):
            await asyncio.sleep(0.3)
            return await super().chat_ex(*a, **k)
    bot.llm = Slow(["labas tau"])
    other = asyncio.create_task(asyncio.sleep(3600))
    await bot.on_message(inc("botucha labas", msg_id=1, ts=9_900.0))
    await asyncio.sleep(0.15)  # the reply is being generated

    await shutdown(bot, [other], drain_s=5)

    assert [t for _, t, _ in out.sent] == ["labas tau"] and other.cancelled()
    assert bot.recover() == 0


async def test_shutdown_saves_what_did_not_finish_in_time(app):
    bot, store, _, out = await app()

    class Hang(FakeLLM):
        async def chat_ex(self, *a, **k):
            await asyncio.sleep(3600)
    bot.llm = Hang([])
    await bot.on_message(inc("botucha labas", msg_id=1, ts=9_900.0))
    await asyncio.sleep(0.15)

    await shutdown(bot, [], drain_s=0.1)

    assert out.sent == []
    saved = []
    bot.worker.submit = lambda j: saved.append(j.msg_id)
    bot.started_at = 1e9  # the next process
    assert bot.recover() == 1 and saved == [1]


async def test_a_background_loop_that_dies_stops_the_bot():
    stopped = []

    async def boom():
        raise RuntimeError("loop died")
    task = asyncio.create_task(boom())
    watch(task, lambda: stopped.append(True))
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert stopped == [True]


async def test_a_cancelled_loop_is_not_a_failure():
    stopped = []
    task = asyncio.create_task(asyncio.sleep(3600))
    watch(task, lambda: stopped.append(True))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert stopped == []
