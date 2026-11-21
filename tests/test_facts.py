from botucha.memory import Memory
from botucha.store import Store
from tests.fakes import FakeEmbedder


def make():
    return Memory(Store(":memory:"), FakeEmbedder(), clock=lambda: 1000.0)


async def test_add_and_delete():
    mem = make()
    fid = await mem.add_fact("fact", "tomas visada veluoja", None, "cmd:1")
    assert [f.text for f in mem.facts_about(None)] == ["tomas visada veluoja"]
    assert mem.delete_fact(fid) is True
    assert mem.delete_fact(fid) is False
    assert mem.facts_about(None) == []


async def test_upsert_merges_near_duplicate():
    mem = make()
    a, new_a = await mem.upsert_fact("fact", "tadas turi daug coreweave akciju ir jas laiko", 5, "auto")
    b, new_b = await mem.upsert_fact("fact", "tadas turi daug coreweave akciju ir jas laiko nvidia", 5, "auto")
    assert new_a is True and new_b is False and a == b
    assert mem.facts_about(5)[0].text.endswith("laiko nvidia")


async def test_upsert_keeps_different():
    mem = make()
    a, _ = await mem.upsert_fact("fact", "tadas turi coreweave", 5, "auto")
    b, new = await mem.upsert_fact("fact", "mantas nemato gta 6", 6, "auto")
    assert new is True and a != b


async def test_update_fact():
    mem = make()
    fid = await mem.add_fact("fact", "senas", None, "auto")
    assert await mem.update_fact(fid, "naujas") is True
    assert mem.facts_about(None)[0].text == "naujas"
    assert await mem.update_fact(9999, "x") is False


async def test_slang_in_matches_token():
    mem = make()
    await mem.add_fact("slang", "zjbs = zajebys", None, "cmd:1")
    assert [f.text for f in mem.slang_in(["cia ZJBS"])] == ["zjbs = zajebys"]
    assert mem.slang_in(["zjbsx"]) == []


async def test_search_facts():
    mem = make()
    await mem.add_fact("fact", "tadas shortina vwce", 5, "auto")
    await mem.add_fact("fact", "tomas veluoja", None, "auto")
    hits = await mem.search_facts("kas shortina vwce", k=1)
    assert hits[0].text == "tadas shortina vwce"


async def test_profiles_roundtrip():
    mem = make()
    mem.set_profile(5, "degenas")
    mem.set_profile(5, "dar didesnis degenas")
    assert mem.profiles() == {5: "dar didesnis degenas"}


TAUGHT = "tadas turi daug coreweave akciju ir jas laiko"
LEARNED = "tadas turi daug coreweave akciju ir jas laiko nvidia"  # near-duplicate for the fake embedder


def row(mem, fid):
    return mem.db.execute("SELECT text, about, source FROM facts WHERE id=?", (fid,)).fetchone()


async def test_auto_fact_never_overwrites_a_member_taught_one():
    mem = make()
    fid = await mem.add_fact("fact", TAUGHT, 5, "cmd:5")
    same, new = await mem.upsert_fact("fact", LEARNED, 6, "auto")
    assert same == fid and new is False
    assert row(mem, fid) == (TAUGHT, 5, "cmd:5")
    assert len(mem.all_facts()) == 1  # and no second, competing fact either


async def test_auto_fact_never_overwrites_a_dashboard_one():
    mem = make()
    fid = await mem.add_fact("fact", TAUGHT, None, "web")
    assert await mem.upsert_fact_ex("fact", LEARNED, 6, "auto") == (fid, "kept")
    assert row(mem, fid) == (TAUGHT, None, "web")


async def test_auto_slang_never_overwrites_member_taught_slang():
    mem = make()
    fid = await mem.add_fact("slang", "saiba = pinigai arba alga uz darba", None, "cmd:5")
    await mem.upsert_fact("slang", "saiba = pinigai arba alga uz darba banke", None, "auto")
    assert row(mem, fid) == ("saiba = pinigai arba alga uz darba", None, "cmd:5")


async def test_auto_update_of_an_auto_fact_also_moves_who_it_is_about():
    mem = make()
    fid, _ = await mem.upsert_fact("fact", TAUGHT, 5, "auto")
    assert await mem.upsert_fact_ex("fact", LEARNED, 6, "auto") == (fid, "updated")
    assert row(mem, fid) == (LEARNED, 6, "auto")
    assert await mem.upsert_fact_ex("fact", LEARNED + " ir", None, "auto") == (fid, "updated")
    assert row(mem, fid)[1] == 6  # an update that names nobody keeps the old link
