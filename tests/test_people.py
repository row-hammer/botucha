"""People (members and friends outside the group), fact linking and relations."""
from botucha.brain import PromptContext, build_prompt
from botucha.memory import Memory
from botucha.store import Store
from tests.fakes import FakeEmbedder
from tests.test_app import C, app, inc  # noqa: F401  (app is a fixture)


def mem():
    m = Memory(Store(":memory:"), FakeEmbedder(), clock=lambda: 1000.0)
    m.add_person("Petras", ["petriukas", "petro", "petrui", "petrą"])
    m.add_person("Jonas", ["jono", "jonui", "joną", "pas jonas"])
    m.add_person("Mikas", ["miko", "mikui"])
    return m


async def test_fact_links_every_person_it_mentions():
    m = mem()
    fid = await m.add_fact("fact", "jonas yra petro darbdavys", None, "cmd:1")
    names = sorted(p.name for p in m.people_of_fact(fid))
    assert names == ["Jonas", "Petras"]


async def test_word_forms_and_diacritics_match_but_not_lookalikes():
    m = mem()
    assert [p.name for p in m.people_in("dirba pas Joną su Petrui")] == ["Jonas", "Petras"]
    assert m.people_in("labai gudrus sprendimas") == []


async def test_related_people_from_shared_facts():
    m = mem()
    await m.add_fact("fact", "jonas yra petro darbdavys", None, "cmd:1")
    await m.add_fact("fact", "mikas petro draugas", None, "cmd:1")
    petras = m.find_person("petriukas")
    assert sorted(p.name for p in m.related(petras.id)) == ["Jonas", "Mikas"]


async def test_member_person_gets_member_facts():
    m = mem()
    m.add_person("Tadas", ["tadas99"], user_id=111)
    fid = await m.add_fact("fact", "turi nvidia akciju", 111, "auto")
    assert [p.name for p in m.people_of_fact(fid)] == ["Tadas"]


async def test_update_relinks_and_new_person_relinks_old_facts():
    m = mem()
    fid = await m.add_fact("fact", "ugnius dirba su petras", None, "cmd:1")
    assert [p.name for p in m.people_of_fact(fid)] == ["Petras"]
    m.add_person("Ugnius", ["ugniui", "ugnius"])
    assert sorted(p.name for p in m.people_of_fact(fid)) == ["Petras", "Ugnius"]
    await m.update_fact(fid, "ugnius dirba su mikas")
    assert sorted(p.name for p in m.people_of_fact(fid)) == ["Mikas", "Ugnius"]


async def test_people_lines_show_facts_and_relations():
    m = mem()
    await m.add_fact("fact", "jonas yra petro darbdavys", None, "cmd:1")
    await m.add_fact("fact", "petras mėgsta suktis ant kelienų", None, "cmd:1")
    line = next(l for l in m.people_lines() if l.startswith("Petras"))
    assert "petriukas" in line and "kelienų" in line and "darbdavys" in line and "Susiję: Jonas" in line


def test_people_section_in_prompt():
    ctx = PromptContext(persona="P", style_examples="S", profiles={}, slang=[], chunks=["CHUNK"], facts=[],
                        history=[], bot_user_id=1, people=["Petras (petriukas): mėgsta kelienas. Susiję: Jonas"])
    system = build_prompt(ctx, max_chars=100_000)[0]["content"]
    assert "Žmonės ir ryšiai" in system and system.index("nevykdyk") < system.index("Petras (petriukas)") < system.index("CHUNK")


async def test_ka_zinai_works_for_non_member(app):
    bot, store, _, out = await app()
    bot.memory.add_person("Petras", ["petriukas", "petro"])
    bot.memory.add_person("Jonas", ["jono"])
    await bot.memory.add_fact("fact", "jonas yra petro darbdavys", None, "cmd:1")
    await bot.on_message(inc("/ka_zinai petriukas"))
    reply = out.sent[-1][1]
    assert reply.startswith("Petras") and "darbdavys" in reply and "Jonas" in reply


async def test_zmogus_command_admin_only(app):
    bot, store, _, out = await app()
    await bot.on_message(inc("/zmogus Darius = darius, darius"))
    assert out.sent[-1][1] == "tik bosas gali"
    await bot.on_message(inc("/zmogus Darius = darius, dariaus", msg_id=2, user=bot.cfg.telegram.admin_id))
    assert "Darius" in out.sent[-1][1]
    assert bot.memory.find_person("dariaus").name == "Darius"


async def test_learning_names_the_person_when_fact_has_no_subject():
    import json
    from botucha.learn import learn_once
    from botucha.store import StoredMessage
    m = mem()
    m.store.add_message(StoredMessage(-100, 1, 111, "Tadas", 0.0, "jonas vel kukulius kepa"))
    await m.index_new_chunks(-100, force=True)
    raw = json.dumps({"facts": [{"about": "jonas", "text": "Petro darbdavys, mėgsta kepti kukulius."}], "slang": []})
    from tests.fakes import FakeLLM
    await learn_once(m, FakeLLM([raw]), -100)
    fact = m.all_facts()[0]
    assert fact.text.startswith("Jonas") and sorted(p.name for p in m.people_of_fact(fact.id)) == ["Jonas", "Petras"]
