from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder

C = -100


def add(store, i, ts, text, name="mantas"):
    store.add_message(StoredMessage(chat_id=C, msg_id=i, user_id=1, name=name, ts=ts, text=text))


def make(now=10_000.0):
    s = Store(":memory:")
    return s, Memory(s, FakeEmbedder(), clock=lambda: now)


async def test_index_is_incremental():
    s, mem = make(now=100_000)
    add(s, 1, 0, "pirmas pokalbis")
    add(s, 2, 4000, "antras pokalbis")
    assert await mem.index_new_chunks(C) == 2
    add(s, 3, 9000, "trecias pokalbis")
    assert await mem.index_new_chunks(C) == 1
    assert await mem.index_new_chunks(C) == 0


async def test_open_chunk_not_indexed_until_closed():
    s, mem = make(now=100)
    add(s, 1, 0, "dar kalbam")
    assert await mem.index_new_chunks(C) == 0
    assert await mem.index_new_chunks(C, force=True) == 1


async def test_search_finds_keyword_chunk():
    s, mem = make(now=100_000)
    add(s, 1, 0, "gta 6 isejo, bet nezaidziau")
    add(s, 2, 4000, "daway uzshortinam vwce")
    add(s, 3, 8000, "sefas vel uzknisa")
    await mem.index_new_chunks(C)
    hits = await mem.search_chunks("kai shortinom vwce", k=3)
    assert "vwce" in hits[0].chunk.text


async def test_fts_special_chars_safe():
    s, mem = make(now=100_000)
    add(s, 1, 0, "spx raudonas")
    await mem.index_new_chunks(C)
    hits = await mem.search_chunks('"spx?" OR (', k=3)
    assert isinstance(hits, list)


async def test_chunks_after():
    s, mem = make(now=100_000)
    add(s, 1, 0, "a")
    await mem.index_new_chunks(C)
    first = mem.chunks_after(C, 0)
    add(s, 2, 4000, "b")
    await mem.index_new_chunks(C)
    later = mem.chunks_after(C, first[-1][0])
    assert [c.text for _, c in later] == ["mantas: b"]
