"""Reply quality: invented words, self-repetition, own lines in history."""
from pathlib import Path

from botucha.brain import PromptContext, generate_reply, generate_reply_ex, is_repeat
from botucha.spell import Speller
from botucha.store import StoredMessage
from tests.fakes import FakeLLM
from tests.test_app import BOT_ID, C, app, inc, settle  # noqa: F401  (app is a fixture)

DICT = Path(__file__).parent.parent / "data" / "hunspell" / "lt"


def ctx():
    return PromptContext(persona="P", style_examples="", profiles={}, slang=[], chunks=[], facts=[],
                         history=[], bot_user_id=BOT_ID)


def test_speller_flags_invented_words_only():
    sp = Speller(DICT, vocab=lambda: {"tsg", "xddd", "vram", "hodlinam", "siandien"})
    assert sp.unknown(["tsg vram'ą šaldau, žiūriu kaip jūs čia varkotės xddd"]) == ["varkotės"]
    assert sp.unknown(["šiandien krenta, hodlinam", "NVDA 125.53 USD −14 %"]) == []
    assert sp.unknown(["kad varna nuosekusi"]) == ["nuosekusi"]


def test_speller_vocab_is_diacritic_insensitive():
    sp = Speller(DICT, vocab=lambda: {"siandien"})
    assert sp.unknown(["šiandien siandien"]) == []


def test_speller_disabled_without_dictionary(tmp_path):
    sp = Speller(tmp_path / "missing", vocab=set)
    assert sp.unknown(["varkotės nuosekusi"]) == []


def test_is_repeat():
    own = ["tsg vram'ą šaldo ir stebiu, kaip jūs čia varkotės xddd", "nu jo"]
    assert is_repeat("tsg vram'ą šaldo ir žiūriu, kaip jūs čia varkotės xddd", own)
    assert is_repeat("Nu jo", own)
    assert not is_repeat("šiandien spx krenta", own)


async def test_a_flagged_word_does_not_cost_a_second_generation():
    """Measured: the retry fixed the spelling 3 times out of 17 and cost a median 7 s every time."""
    llm = FakeLLM(["kad varna nuosekusi xdd", "kad greičiau baigtųsi"])
    sp = Speller(DICT, vocab=lambda: {"xdd"})
    res = await generate_reply_ex(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], speller=sp)
    assert res.texts == ["kad varna nuosekusi xdd"] and res.fallback and len(llm.calls) == 1


async def test_an_uninvited_reply_with_a_flagged_word_stays_quiet():
    llm = FakeLLM(["kad varna nuosekusi xdd", "kad greičiau baigtųsi"])
    sp = Speller(DICT, vocab=lambda: {"xdd"})
    res = await generate_reply_ex(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], speller=sp,
                                  direct=False)
    assert res.texts is None and res.quiet and len(llm.calls) == 1


async def test_a_direct_call_is_never_silent_because_of_the_dictionary():
    own = ["sena eilute apie nieka"]
    llm = FakeLLM(["sena eilute apie nieka\nvarkotės nuosekusi dygimai", "šiandien varkotės"])
    sp = Speller(DICT, vocab=set)
    res = await generate_reply_ex(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], speller=sp,
                                  recent_own=own)
    # attempt 1 also repeated himself, so it was generated again; of the two flagged drafts the cleaner one goes out
    assert res.texts == ["šiandien varkotės"] and res.fallback and len(llm.calls) == 2


async def test_an_uninvited_reply_that_is_flagged_twice_stays_quiet():
    own = ["sena eilute apie nieka"]
    llm = FakeLLM(["sena eilute apie nieka\nvarkotės nuosekusi dygimai", "šiandien varkotės"])
    res = await generate_reply_ex(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[],
                                  speller=Speller(DICT, vocab=set), recent_own=own, direct=False)
    assert res.texts is None and res.quiet


async def test_quiet_on_purpose_is_not_reported_as_an_error(app):
    bot, store, llm, out = await app(["kad varna nuosekusi"], rng_value=0.0)  # rng 0.0: an uninvited reply triggers
    bot.speller = Speller(DICT, vocab=set)
    await bot.on_message(inc("siaip snekam apie orus"))
    await settle()
    assert out.sent == [] and len(llm.calls) == 1
    assert not bot.last_error


async def test_repeated_line_dropped_or_retried():
    own = ["tsg neas tavo excelas xddd"]
    llm = FakeLLM(["tsg neas tavo excelas xddd\nqqq tik kyla", "x"])
    out = await generate_reply(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], recent_own=own)
    assert out == ["qqq tik kyla"]
    llm = FakeLLM(["tsg neas tavo excelas xddd", "kitas atsakymas"])
    out = await generate_reply(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], recent_own=own)
    assert out == ["kitas atsakymas"]


async def test_history_keeps_only_last_five_own_lines(app):
    bot, store, llm, out = await app(["naujas"])
    for i in range(12):
        store.add_message(StoredMessage(C, 300 + i, BOT_ID, "Botucha", 9000.0 + i, f"senas{i}", is_bot=True))
    await bot.on_message(inc("botucha ka manai", msg_id=400))
    await settle()
    user = llm.calls[0]["messages"][1]["content"]
    assert "senas11" in user and "senas7" in user and "senas6" not in user and "senas0" not in user


async def test_vocab_comes_from_members_not_bot(app):
    bot, store, _, _ = await app()
    store.add_message(StoredMessage(C, 500, 111, "Tadas", 1.0, "kapazocha visur"))
    store.add_message(StoredMessage(C, 501, BOT_ID, "Botucha", 2.0, "varkotės", is_bot=True))
    vocab = bot.vocabulary()
    assert "kapazocha" in vocab and "varkotes" not in vocab


async def test_commands_not_in_prompt_history(app):
    bot, store, llm, out = await app(["jo"])
    store.add_message(StoredMessage(C, 600, 111, "Tadas", 9000.0, "/pataisyk geriau taip"))
    store.add_message(StoredMessage(C, 601, 111, "Tadas", 9001.0, "/gerai"))
    store.add_message(StoredMessage(C, 602, 111, "Tadas", 9002.0, "vakar buvo smagu"))
    await bot.on_message(inc("botucha ka manai", msg_id=603))
    await settle()
    user = llm.calls[0]["messages"][1]["content"]
    assert "vakar buvo smagu" in user and "/pataisyk" not in user and "/gerai" not in user


async def test_rimtai_question_stays_in_history(app):
    bot, store, llm, out = await app(["atsakymas"])
    await bot.on_message(inc("/rimtai kaip veikia etf", msg_id=610))
    await settle()
    user = llm.calls[0]["messages"][1]["content"]
    assert "kaip veikia etf" in user


def test_speller_skips_names_inside_a_sentence():
    sp = Speller(DICT, vocab=set)
    assert sp.unknown(["pirkau Vanguard fondą, Bonnie Blue irgi"]) == []


def test_speller_skips_a_two_word_name_that_starts_a_sentence():
    sp = Speller(DICT, vocab=set)
    assert sp.unknown(["Bonnie Blue vėl naujienose. o Varkotės čia"]) == []
    assert sp.unknown(["Varkotės čia."]) == ["Varkotės"]  # one capital at the start proves nothing


def test_speller_still_checks_the_first_word_of_a_sentence():
    sp = Speller(DICT, vocab=set)
    assert sp.unknown(["Varkotės čia. Nuosekusi varna! Skrietėti?"]) == ["Varkotės", "Nuosekusi", "Skrietėti"]


async def test_min_p_from_config_is_sent():
    from botucha.config import ModelCfg
    from botucha.llm import OllamaLLM
    llm = OllamaLLM(ModelCfg("m", "e", 1024, 10, "1m", "http://localhost:11434", temperature=0.6, min_p=0.05))
    seen = {}

    async def fake_chat(**kw):
        seen.update(kw)
        return {"message": {"content": "ok"}}

    llm.client.chat = fake_chat
    await llm.chat([{"role": "user", "content": "x"}], num_predict=5)
    assert seen["options"]["min_p"] == 0.05 and seen["options"]["temperature"] == 0.6


def test_min_p_missing_from_old_config_uses_default(tmp_path):
    from botucha.config import ModelCfg, load_config
    src = (Path(__file__).parent.parent / "config.example.toml").read_text()
    p = tmp_path / "config.toml"
    p.write_text("\n".join(l for l in src.splitlines() if not l.startswith("min_p")))
    assert load_config(p, {"BOTUCHA_TOKEN": "t"}).model.min_p == ModelCfg.min_p


async def test_names_he_was_told_about_are_group_vocabulary(app):
    """People, their word forms, and the words of facts a person wrote: none of that is an invented word."""
    bot, store, _, _ = await app()
    bot.memory.add_person("Vanguardas", ["vangardo"])
    await bot.memory.add_fact("fact", "Jonas dirba Kaliningrade", None, "cmd:111")
    await bot.memory.add_fact("fact", "Jonas megsta Zoviraksa", None, "web")
    await bot.memory.add_fact("fact", "Jonas megsta Isgalvotuma", None, "auto")  # the model's own wording proves nothing
    words = bot.vocabulary()
    assert {"vanguardas", "vangardo", "kaliningrade", "zoviraksa"} <= words and "isgalvotuma" not in words
