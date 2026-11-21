"""A restart or a crash never silently drops a reply someone asked for, and never leaves a trace open."""
import asyncio
import random
import sqlite3

from botucha.app import RECOVER_S, Botucha, ReplyJob
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from botucha.trace import Tracer
from tests.fakes import FakeEmbedder, FakeLLM
from tests.test_app import BOT_ID, C, FakeOutbox, inc, make_cfg, nosleep

NOW = 10_000.0


def make_bot(tmp_path, store=None, responses=(), now=NOW):
    store = store or Store(":memory:")
    rng = random.Random(0)
    rng.random = lambda: 0.99
    bot = Botucha(make_cfg(tmp_path), store, Memory(store, FakeEmbedder(), clock=lambda: now), FakeLLM(list(responses)),
                  FakeOutbox(), rng=rng, clock=lambda: now, bot_user_id=BOT_ID, bot_username="botucha_bot",
                  sleep=nosleep, started_at=now)
    bot.tracer = Tracer(store, clock=lambda: now)
    return bot, store


class Hang(FakeLLM):
    async def chat_ex(self, *a, **k):
        await asyncio.sleep(30)


async def crash_during(bot, jobs):
    """The process dies while answering: the task is torn down mid-generation."""
    bot.llm = Hang([])
    task = asyncio.create_task(bot.run_job(jobs))
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def ask(store, msg_id, ts, text="botucha labas", chat=C):
    store.add_message(StoredMessage(chat, msg_id, 111, "Tadas", ts, text))


async def run_worker_once(bot):
    task = asyncio.create_task(bot.worker.run())
    await asyncio.sleep(0.2)
    await bot.worker.stop()
    task.cancel()


async def test_a_reply_cut_off_by_a_crash_is_answered_after_the_restart(tmp_path):
    db = tmp_path / "botucha.db"
    bot, store = make_bot(tmp_path, store=Store(db))
    ask(store, 1, NOW - 5)
    await crash_during(bot, [ReplyJob(C, 1, True, False, False, "direct")])
    store.conn.close()

    bot2, store2 = make_bot(tmp_path, store=Store(db), responses=["labas tau"], now=NOW + 40)
    assert bot2.recover() == 1
    await run_worker_once(bot2)

    assert [(t, mid) for _, t, mid in bot2.outbox.sent] == [("labas tau", 1)]
    first = store2.conn.execute("SELECT outcome, error FROM traces ORDER BY id").fetchone()
    assert first[0] == "error" and "interrupted" in first[1]
    assert store2.conn.execute("SELECT COUNT(*) FROM traces WHERE outcome IS NULL").fetchone()[0] == 0
    assert bot2.recover() == 0  # and not a second time


async def test_only_recent_direct_calls_come_back(tmp_path):
    bot, store = make_bot(tmp_path, responses=["x", "y", "z"])
    ask(store, 1, NOW - 60)                 # uninvited: nobody is waiting for it
    ask(store, 2, NOW - RECOVER_S - 60)     # too long ago: an answer now would be odd
    ask(store, 3, NOW - 30)                 # a direct call in the same burst as 1
    bot.save_pending([ReplyJob(C, 1, False, False, False, "random:1/25"), ReplyJob(C, 2, True, False, False, "direct"),
                      ReplyJob(C, 3, True, False, False, "direct"), ReplyJob(C, 99, True, False, False, "direct")])

    assert bot.recover() == 1
    await run_worker_once(bot)

    assert [mid for _, _, mid in bot.outbox.sent] == [3]


async def test_a_serious_call_comes_back_serious_with_its_links_flag(tmp_path):
    bot, store = make_bot(tmp_path)
    ask(store, 1, NOW - 30, "/rimtai kas yra etf")
    ask(store, 2, NOW - 30, "/atsimeni kai shortinom")
    bot.save_pending([ReplyJob(C, 1, True, True, False, "serious"), ReplyJob(C, 2, True, False, True, "recall", links=True)])
    jobs = []
    bot.worker.submit = jobs.append
    bot.recover()
    assert [(j.serious, j.recall, j.links) for j in jobs] == [(True, False, False), (False, True, True)]


async def test_replies_not_finished_at_shutdown_are_answered_after_the_restart(tmp_path):
    db = tmp_path / "botucha.db"
    bot, store = make_bot(tmp_path, store=Store(db))
    store.add_message(StoredMessage(C, 7, 111, "Tadas", NOW - 5, "/rimtai kas yra etf"))
    bot.save_pending([ReplyJob(C, 7, direct=True, serious=True, recall=False, trigger="serious"),
                      ReplyJob(C, 8, direct=False, serious=False, recall=False, trigger="random:1/25")])
    store.conn.close()

    bot2, store2 = make_bot(tmp_path, store=Store(db), responses=["etf yra fondas"], now=NOW + 30)
    jobs = []
    real = bot2.worker.submit
    bot2.worker.submit = lambda j: (jobs.append(j), real(j))
    assert bot2.recover() == 1
    await run_worker_once(bot2)

    assert [(j.msg_id, j.serious) for j in jobs] == [(7, True)]
    assert bot2.outbox.sent and bot2.outbox.sent[0][2] == 7
    assert store2.get_state("pending_replies") in (None, "", "[]")  # never answered twice


async def test_a_store_error_in_one_chat_does_not_cost_the_others_their_reply(tmp_path):
    other = 4242
    bot, store = make_bot(tmp_path, responses=["labas rytas", "labas vakaras"])
    import dataclasses
    bot.cfg = dataclasses.replace(bot.cfg, telegram=dataclasses.replace(bot.cfg.telegram, chat_ids=(C, other)))
    for chat, mid in ((C, 1), (other, 2)):
        store.add_message(StoredMessage(chat, mid, 111, "Tadas", NOW - 1, "botucha labas"))
    real = store.add_message

    def failing(m):
        if m.is_bot and m.chat_id == C:
            raise sqlite3.OperationalError("database is locked")
        return real(m)
    store.add_message = failing

    await bot.run_job([ReplyJob(C, 1, True, False, False, "direct"), ReplyJob(other, 2, True, False, False, "direct")])

    assert {chat for chat, _, _ in bot.outbox.sent} == {C, other}
    assert store.conn.execute("SELECT COUNT(*) FROM traces WHERE outcome IS NULL").fetchone()[0] == 0
    assert "locked" in bot.last_error


async def test_an_interrupted_reply_closes_its_trace(tmp_path):
    bot, store = make_bot(tmp_path)
    ask(store, 1, NOW - 1)
    await crash_during(bot, [ReplyJob(C, 1, True, False, False, "direct")])
    outcome, error = store.conn.execute("SELECT outcome, error FROM traces").fetchone()
    assert outcome == "error" and "interrupted" in error


async def test_a_finished_batch_leaves_nothing_pending(tmp_path):
    bot, store = make_bot(tmp_path, responses=["labas"])
    ask(store, 1, NOW - 1)
    await bot.run_job([ReplyJob(C, 1, True, False, False, "direct")])
    assert bot.recover() == 0 and store.get_state("pending_replies") in (None, "", "[]")
