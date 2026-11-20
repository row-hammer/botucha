import json

from botucha.learn import learn_once
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder, FakeLLM
from tests.test_app import C as APP_C, app, inc, settle  # noqa: F401  (app is a fixture)


def mem():
    return Memory(Store(":memory:"), FakeEmbedder(), clock=lambda: 1000.0)


async def test_all_slang_prefers_member_taught_and_dedupes():
    m = mem()
    await m.add_fact("slang", "saibos = akcijos", None, "auto")
    await m.add_fact("slang", "saiba = bezdalas", None, "cmd:111")
    await m.add_fact("slang", "kdn = kedainiai", None, "cmd:222")
    await m.add_fact("slang", "kdn = Kedainiai", None, "auto")
    await m.add_fact("slang", "pituchas = gaidys", None, "cmd:111")
    await m.add_fact("slang", "pituchas = gaidys / zmogus", None, "auto")
    got = m.all_slang()
    assert "saiba = bezdalas" in got and "saibos = akcijos" not in got  # same stem, member wins
    assert sorted(t for t in got if t.startswith("kdn")) == ["kdn = kedainiai"]
    assert [t for t in got if t.startswith("pituchas")] == ["pituchas = gaidys"]


async def test_newest_auto_wins_when_no_member_entry():
    m = mem()
    await m.add_fact("slang", "tsg = kazkas", None, "auto")
    m.clock = lambda: 2000.0
    await m.add_fact("slang", "tsg = trumpai sakant", None, "auto")
    assert m.all_slang() == ["tsg = trumpai sakant"]


async def test_prompt_gets_all_slang_not_only_mentioned(app):
    bot, store, llm, out = await app(["jo"])
    await bot.memory.add_fact("slang", "kapazocha = zona", None, "cmd:111")
    await bot.on_message(inc("botucha ka veiki"))
    await settle()
    assert "kapazocha = zona" in llm.calls[0]["messages"][0]["content"]


async def test_learning_ignores_botucha_lines():
    s = Store(":memory:")
    s.upsert_member(111, "Tadas", None)
    s.add_message(StoredMessage(-100, 1, 111, "Tadas", 0.0, "kapazocha visur"))
    s.add_message(StoredMessage(-100, 2, 999, "Botucha", 5.0, "vram glichiuoja xdd", is_bot=True))
    m = Memory(s, FakeEmbedder(), clock=lambda: 100_000.0)
    await m.index_new_chunks(-100)
    llm = FakeLLM([json.dumps({"facts": [], "slang": []})])
    await learn_once(m, llm, -100)
    sent = llm.calls[0]["messages"][1]["content"]
    assert "kapazocha visur" in sent and "vram glichiuoja" not in sent
