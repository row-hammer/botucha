"""Reply quality: invented words, self-repetition, own lines in history."""
from pathlib import Path

from botucha.brain import PromptContext, generate_reply, is_repeat
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


async def test_invented_word_triggers_retry():
    llm = FakeLLM(["kad varna nuosekusi xdd", "kad greičiau baigtųsi"])
    sp = Speller(DICT, vocab=lambda: {"xdd"})
    out = await generate_reply(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], speller=sp)
    assert out == ["kad greičiau baigtųsi"] and len(llm.calls) == 2


async def test_two_bad_attempts_send_the_cleaner_one():
    llm = FakeLLM(["varkotės nuosekusi dygimai", "šiandien varkotės"])
    sp = Speller(DICT, vocab=set)
    out = await generate_reply(llm, ctx(), num_predict=50, max_chars=10_000, member_names=[], speller=sp)
    assert out == ["šiandien varkotės"]  # never silent because of the dictionary


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
