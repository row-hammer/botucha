"""Indexing a backlog: bounded embedding requests, progress kept, and never in the way of a reply."""
import pytest

from botucha.app import CANNED
from botucha.memory import EMBED_BATCH, Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder
from tests.test_app import C, app, inc, settle  # noqa: F401  (app is a fixture)


class CountingEmbedder(FakeEmbedder):
    def __init__(self, fail_on_call=None):
        super().__init__()
        self.sizes, self.fail_on_call = [], fail_on_call

    async def embed(self, texts):
        if self.fail_on_call is not None and len(self.sizes) + 1 >= self.fail_on_call:
            raise TimeoutError("embedding timed out")
        self.sizes.append(len(texts))
        return await super().embed(texts)


def backlog(n, store=None, start=0.0):
    """n conversations an hour apart: one chunk each."""
    s = store or Store(":memory:")
    for i in range(n):
        s.add_message(StoredMessage(C, i + 1, 111, "Tadas", start + i * 4000.0, f"pokalbis{i} apie akcijas"))
    return s


def chunk_count(s):
    return s.conn.execute("SELECT COUNT(*), COUNT(DISTINCT first_msg_id) FROM chunks").fetchone()


async def test_a_backlog_is_embedded_in_bounded_requests():
    s = backlog(100)
    emb = CountingEmbedder()
    n = await Memory(s, emb, clock=lambda: 1e9).index_new_chunks(C, force=True)
    assert n == 100 and sum(emb.sizes) == 100
    assert len(emb.sizes) > 1 and max(emb.sizes) <= EMBED_BATCH


async def test_progress_is_kept_when_an_embedding_request_fails():
    s = backlog(100)
    mem = Memory(s, CountingEmbedder(fail_on_call=3), clock=lambda: 1e9)

    with pytest.raises(TimeoutError):
        await mem.index_new_chunks(C, force=True)

    assert chunk_count(s) == (2 * EMBED_BATCH, 2 * EMBED_BATCH)  # the first two requests are not thrown away
    mem.embedder = CountingEmbedder()
    await mem.index_new_chunks(C, force=True)
    assert chunk_count(s) == (100, 100)  # and nothing is indexed twice
    assert sum(mem.embedder.sizes) == 100 - 2 * EMBED_BATCH


async def test_limit_caps_the_work_of_one_call():
    s = backlog(100)
    mem = Memory(s, CountingEmbedder(), clock=lambda: 1e9)
    assert await mem.index_new_chunks(C, force=True, limit=EMBED_BATCH) == EMBED_BATCH
    assert mem.embedder.sizes == [EMBED_BATCH]
    assert await mem.index_new_chunks(C, force=True) == 100 - EMBED_BATCH


async def test_a_reply_indexes_only_one_request_of_a_backlog(app):
    bot, store, _, out = await app(["labas tau"])
    backlog(100, store, start=-500_000.0)
    bot.memory.embedder = CountingEmbedder()

    await bot.on_message(inc("botucha labas", msg_id=1000))
    await settle()

    assert out.sent[-1][1] == "labas tau"
    assert chunk_count(store)[0] == EMBED_BATCH
    assert max(bot.memory.embedder.sizes) <= EMBED_BATCH


async def test_a_reply_goes_out_when_the_memory_search_is_down(app):
    bot, store, _, out = await app(["labas tau"])
    backlog(5, store, start=-500_000.0)
    bot.memory.embedder = CountingEmbedder(fail_on_call=1)  # the embedding model is gone; the chat model is fine

    await bot.on_message(inc("botucha labas", msg_id=1000))
    await settle()

    assert [t for _, t, _ in out.sent] == ["labas tau"] and CANNED not in out.sent[-1][1]
