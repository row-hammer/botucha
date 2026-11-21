from tests.test_app import app  # noqa: F401  (app is a fixture)
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


class FixedEmbedder:
    """Chosen vectors per text, so the test controls which chunks are close in meaning."""

    def __init__(self, vectors, default=(0.0, 0.0, 1.0)):
        self.vectors, self.default = vectors, default

    async def embed(self, texts):
        import numpy as np
        v = np.array([self.vectors.get(t, self.default) for t in texts], dtype=np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


async def test_a_rare_word_finds_its_conversation_even_when_others_are_closer_in_meaning():
    """Before: FTS hits joined the cosine top 10 but the result was still cut by cosine, so a k of 3, 6 or 10
    always returned exactly the cosine top k and the only chunk with the searched word was never found."""
    s = Store(":memory:")
    vec = {}
    for i in range(12):
        vec[f"mantas: pokalbis apie orus numeris {i}"] = [1.0, 0.01 * i, 0.0]
    vec["mantas: tadas pirko zoviraksas akciju"] = [0.2, 1.0, 0.0]
    vec["kas pirko zoviraksas"] = [1.0, 0.0, 0.0]
    mem = Memory(s, FixedEmbedder(vec), clock=lambda: 1e9)
    for i, text in enumerate(t for t in vec if t.startswith("mantas: ")):
        add(s, i + 1, i * 4000.0, text.removeprefix("mantas: "))
    await mem.index_new_chunks(C, force=True)
    for k in (3, 6):
        hits = await mem.search_chunks("kas pirko zoviraksas", k=k, chat_id=C)
        assert any("zoviraksas" in h.chunk.text for h in hits), k
        assert next(h for h in hits if "zoviraksas" in h.chunk.text).fts


async def test_meaning_still_ranks_when_no_word_matches():
    s, mem = make(now=100_000)
    add(s, 1, 0, "gta 6 isejo, bet nezaidziau")
    add(s, 2, 4000, "daway uzshortinam vwce")
    await mem.index_new_chunks(C)
    hits = await mem.search_chunks("qqq zzz", k=2)
    assert len(hits) == 2 and not any(h.fts for h in hits)


async def test_chunks_from_the_visible_conversation_are_not_retrieved_again():
    s, mem = make(now=100_000)
    add(s, 1, 0, "vwce shortinam senai")
    add(s, 2, 4000, "vwce shortinam vakar")
    add(s, 3, 8000, "vwce shortinam dabar")
    await mem.index_new_chunks(C)
    hits = await mem.search_chunks("vwce shortinam", k=3, chat_id=C, before_msg_id=2)
    assert [h.chunk.first_msg_id for h in hits] == [1]


async def test_a_reply_does_not_get_back_what_is_already_in_its_transcript(app):
    from tests.test_app import inc, settle
    bot, store, llm, _ = await app(["nu jo"])
    for i in range(20):
        store.add_message(StoredMessage(-1001234567890, i + 1, 111, "Tadas", i * 60.0, f"nvidia akcijos kyla {i}"))
    await bot.memory.index_new_chunks(-1001234567890, force=True)
    await bot.on_message(inc("botucha nvidia akcijos", msg_id=100))
    await settle()
    assert "Ka prisimeni" not in llm.calls[-1]["messages"][1]["content"]  # every chunk is in the last 40 lines


async def test_one_reply_embeds_its_query_once():
    s, mem = make(now=100_000)
    add(s, 1, 0, "daway uzshortinam vwce")
    await mem.index_new_chunks(C)
    await mem.add_fact("fact", "tadas shortina vwce", None, "cmd:1")
    before = mem.embedder.calls
    await mem.search_chunks("kai shortinom vwce", k=3)
    await mem.search_facts_scored("kai shortinom vwce", k=5)
    assert mem.embedder.calls - before == 1


async def test_the_embedding_model_stays_loaded_as_long_as_the_chat_model():
    from botucha.embed import OllamaEmbedder
    seen = {}

    async def fake_embed(**kw):
        seen.update(kw)
        return {"embeddings": [[1.0, 0.0]]}
    e = OllamaEmbedder("http://localhost:11434", "bge-m3", keep_alive="30m")
    e.client.embed = fake_embed
    await e.embed(["labas"])
    assert seen["keep_alive"] == "30m" and seen["options"] == {"num_gpu": 0}
