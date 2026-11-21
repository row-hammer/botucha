import json

from botucha.learn import learn_once, parse_extraction, profiles_due, refresh_profiles, should_learn
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder, FakeLLM

C = -100


def setup():
    s = Store(":memory:")
    s.upsert_member(111, "Tadas", "tadas")
    s.upsert_member(222, "mantas", None)
    s.add_message(StoredMessage(C, 1, 111, "Tadas", 0.0, "uzshortinau vwce su 3x"))
    s.add_message(StoredMessage(C, 2, 222, "mantas", 5.0, "zjbs xdd"))
    return s, Memory(s, FakeEmbedder(), clock=lambda: 100_000.0)


GOOD = json.dumps({"facts": [{"about": "tada", "text": "tadas shortina vwce su 3x"}],
                   "slang": [{"word": "zjbs", "meaning": "zajebys, labai gerai"}]})


def test_parse_valid():
    e = parse_extraction(GOOD)
    assert e.facts == [("tada", "tadas shortina vwce su 3x")]
    assert e.slang == [("zjbs", "zajebys, labai gerai")]


def test_parse_garbage_returns_none():
    assert parse_extraction("lol") is None
    assert parse_extraction('{"facts": 3}') is None


def test_parse_skips_empty_items():
    e = parse_extraction(json.dumps({"facts": [{"about": None, "text": ""}], "slang": [{"word": "x", "meaning": ""}]}))
    assert e.facts == [] and e.slang == []


def test_should_learn_rules():
    kw = dict(now=1000.0, last_msg_ts=0.0, new_msgs=30, reply_pending=False)
    assert should_learn(**kw) is True
    assert should_learn(**{**kw, "last_msg_ts": 500.0}) is False
    assert should_learn(**{**kw, "new_msgs": 29}) is False
    assert should_learn(**{**kw, "reply_pending": True}) is False


async def test_learn_once_writes_and_advances():
    s, mem = setup()
    await mem.index_new_chunks(C)
    assert await learn_once(mem, FakeLLM([GOOD]), C) == 2
    assert mem.facts_about(111)[0].text == "tadas shortina vwce su 3x"
    assert [f.text for f in mem.slang_in(["zjbs"])] == ["zjbs = zajebys, labai gerai"]
    assert await learn_once(mem, FakeLLM([GOOD]), C) == 0  # nothing new


async def test_learn_once_garbage_writes_nothing():
    s, mem = setup()
    await mem.index_new_chunks(C)
    assert await learn_once(mem, FakeLLM(["not json"]), C) == 0
    assert mem.all_facts() == []
    assert await learn_once(mem, FakeLLM([GOOD]), C) == 2  # cursor did not move


async def test_name_mapping_prefix():
    s, mem = setup()
    await mem.index_new_chunks(C)
    await learn_once(mem, FakeLLM([GOOD]), C)
    assert mem.facts_about(111) and not mem.facts_about(222)


async def test_refresh_profiles():
    s, mem = setup()
    llm = FakeLLM(["degenas su 3x", "tylus zjbs zmogus"])
    await refresh_profiles(mem, llm, s, C)
    assert mem.profiles() == {111: "degenas su 3x", 222: "tylus zjbs zmogus"}
    assert profiles_due(s, C, every=200) is False


def test_profiles_due():
    s, _ = setup()
    assert profiles_due(s, C, every=2) is True
    assert profiles_due(s, C, every=3) is False


async def test_locked_member_gets_no_auto_facts():
    s, mem = setup()
    await mem.index_new_chunks(C)
    raw = json.dumps({"facts": [{"about": "tada", "text": "tadas vel shortina"},
                                {"about": "mantas", "text": "mantas zaidzia gta"}], "slang": []})
    assert await learn_once(mem, FakeLLM([raw]), C, locked=frozenset({111})) == 1
    assert mem.facts_about(111) == [] and mem.facts_about(222)


async def test_locked_member_profile_not_refreshed():
    s, mem = setup()
    mem.set_profile(111, "rankinis profilis")
    await refresh_profiles(mem, FakeLLM(["naujas mantas profilis"]), s, C, locked=frozenset({111}))
    assert mem.profiles() == {111: "rankinis profilis", 222: "naujas mantas profilis"}


def test_config_locked_members(tmp_path):
    from pathlib import Path
    from botucha.config import load_config
    ex = Path(__file__).parent.parent / "config.example.toml"
    assert load_config(ex, {"BOTUCHA_TOKEN": "t"}).memory.locked_members == ()
    p = tmp_path / "c.toml"
    p.write_text(ex.read_text() + "\n[memory]\nlocked_members = [111]\n")
    assert load_config(p, {"BOTUCHA_TOKEN": "t"}).memory.locked_members == (111,)


async def test_learning_leaves_a_member_taught_fact_alone_and_says_so():
    from botucha.trace import Tracer
    s, mem = setup()
    await mem.index_new_chunks(C)
    fid = await mem.add_fact("fact", "tadas shortina vwce su 3x svertu kasdien", 111, "cmd:111")
    raw = json.dumps({"facts": [{"about": "tada", "text": "tadas shortina vwce su 3x svertu kasdien ryte"}], "slang": []})
    run = Tracer(s).start("learn", chat_id=C)
    assert await learn_once(mem, FakeLLM([raw]), C, run=run) == 0
    assert [f.text for f in mem.all_facts()] == ["tadas shortina vwce su 3x svertu kasdien"]
    detail = json.loads(s.conn.execute("SELECT detail FROM trace_steps WHERE kind='facts'").fetchone()[0])
    assert detail["added"] == [] and [r["reason"] for r in detail["rejected"]] == ["curated"]
