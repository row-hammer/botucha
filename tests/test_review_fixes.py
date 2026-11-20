"""Regression tests for the final-review findings."""
import asyncio

from botucha.config import ModelCfg
from botucha.llm import OllamaLLM
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder
from tests.test_app import BOT_ID, C, FIX, app, inc, settle  # noqa: F401  (app is a fixture)


class SlowEmbedder(FakeEmbedder):
    async def embed(self, texts):
        await asyncio.sleep(0.05)
        return await super().embed(texts)


class BrokenEmbedder(FakeEmbedder):
    async def embed(self, texts):
        raise ConnectionError("ollama down")


async def test_concurrent_indexing_does_not_duplicate():
    s = Store(":memory:")
    s.add_message(StoredMessage(C, 1, 1, "a", 0.0, "vienas"))
    mem = Memory(s, SlowEmbedder(), clock=lambda: 100_000.0)
    await asyncio.gather(mem.index_new_chunks(C), mem.index_new_chunks(C, force=True))
    assert s.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 1


async def test_bootstrap_and_learn_tick_do_not_both_learn(app):
    bot, store, llm, _ = await app(['{"facts": [], "slang": []}'] + ["p"] * 10, export=FIX)
    bot.clock = lambda: 1e12  # everything looks idle and old
    await asyncio.gather(bot.bootstrap(), bot.learn_tick())
    assert sum(c["fmt_json"] for c in llm.calls) == 1


async def test_chunk_search_scoped_to_chat():
    s = Store(":memory:")
    s.add_message(StoredMessage(-1, 1, 1, "a", 0.0, "vwce shortinam"))
    s.add_message(StoredMessage(-2, 1, 1, "a", 0.0, "vwce kitas chatas"))
    mem = Memory(s, FakeEmbedder(), clock=lambda: 100_000.0)
    await mem.index_new_chunks(-1)
    await mem.index_new_chunks(-2)
    hits = await mem.search_chunks("vwce", k=5, chat_id=-1)
    assert hits and all(h.chunk.chat_id == -1 for h in hits)


async def test_stale_command_not_executed_or_answered(app):
    bot, _, _, out = await app()
    await bot.on_message(inc("/tyla 60", ts=10.0))  # sent before start
    assert out.sent == [] and bot.state.quiet_until == 0.0


async def test_command_error_is_reported(app):
    bot, store, llm, out = await app()
    bot.memory.embedder = BrokenEmbedder()
    await bot.on_message(inc("/isimink tomas veluoja"))
    assert out.sent and "nepavyko" in out.sent[-1][1]
    assert "ConnectionError" in bot.last_error


async def test_long_command_reply_truncated(app):
    bot, _, _, out = await app()
    for i in range(80):
        await bot.memory.add_fact("fact", "tadas " + "labai ilgas faktas " * 5 + str(i), 111, "auto")
    await bot.on_message(inc("/ka_zinai"))
    assert len(out.sent[-1][1]) <= 4000


async def test_learn_tick_survives_store_errors(app):
    bot, store, _, _ = await app()

    def boom(*a, **k):
        raise RuntimeError("db locked")

    store.recent_messages = boom
    await bot.learn_tick()
    assert "db locked" in bot.last_error


def test_ollama_client_has_timeout():
    cfg = ModelCfg("m", "e", 1024, 10, "1m", "http://localhost:11434")
    assert OllamaLLM(cfg).client._client.timeout.read >= 120


def test_example_config_has_no_private_values():
    text = (FIX.parent.parent.parent / "config.example.toml").read_text()
    for private in ("100000001", "1234567890", "/home/user"):
        assert private not in text


async def test_temperature_from_config_is_sent():
    cfg = ModelCfg("m", "e", 1024, 10, "1m", "http://localhost:11434", temperature=0.6)
    llm = OllamaLLM(cfg)
    seen = {}

    async def fake_chat(**kw):
        seen.update(kw)
        return {"message": {"content": "ok"}}

    llm.client.chat = fake_chat
    await llm.chat([{"role": "user", "content": "x"}], num_predict=5)
    assert seen["options"]["temperature"] == 0.6


def test_example_config_temperature():
    from botucha.config import load_config
    cfg = load_config(FIX.parent.parent.parent / "config.example.toml", {"BOTUCHA_TOKEN": "t"})
    assert cfg.model.temperature == 0.7
