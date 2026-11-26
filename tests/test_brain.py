from tests.test_app import app  # noqa: F401  (app is a fixture)
from botucha.brain import PromptContext, build_prompt, clean_reply, generate_reply
from botucha.store import StoredMessage
from tests.fakes import FakeLLM

BOT = 999


def msg(i, text, user=1, name="Tadas"):
    return StoredMessage(chat_id=-1, msg_id=i, user_id=user, name=name, ts=float(i), text=text)


def ctx(history=None, serious=False):
    return PromptContext(
        persona="PERSONA", style_examples="STYLE", profiles={"Tadas": "PROFILE"},
        slang=["zjbs = zajebys"], chunks=["CHUNK"], facts=["FACT"],
        history=history or [msg(1, "spx raudonas")], bot_user_id=BOT, serious=serious)


def test_section_order():
    whole = "\n".join(m["content"] for m in build_prompt(ctx(), max_chars=100_000))
    idx = [whole.index(s) for s in ("PERSONA", "STYLE", "PROFILE", "zjbs", "spx raudonas", "CHUNK", "FACT")]
    assert idx == sorted(idx)  # stable parts, the transcript, then what was retrieved for this reply


def test_bot_lines_labelled():
    hist = [msg(1, "ka manai"), msg(2, "hodlinam", user=BOT, name="Botucha")]
    user = build_prompt(ctx(hist), max_chars=100_000)[1]["content"]
    assert "Tadas: ka manai" in user and "botucha: hodlinam" in user


def test_history_trim_keeps_newest():
    hist = [msg(i, f"m{i:02d} " + "x" * 500) for i in range(40)]
    user = build_prompt(ctx(hist), max_chars=3000)[1]["content"]
    assert "m39" in user and "m00" not in user
    total = sum(len(m["content"]) for m in build_prompt(ctx(hist), max_chars=3000))
    assert total <= 3000


def test_huge_single_message_truncated():
    user = build_prompt(ctx([msg(1, "y" * 50_000)]), max_chars=4000)[1]["content"]
    assert len(user) <= 1000 + 200


def test_serious_mode_line():
    normal = build_prompt(ctx(), max_chars=100_000)[1]["content"]
    serious = build_prompt(ctx(serious=True), max_chars=100_000)[1]["content"]
    assert len(serious) > len(normal) and "rimtai" in serious.lower()


def test_clean_strips_member_prefix():
    assert clean_reply("Tadas: hodlinam\nxdd", ["Tadas"]) == ["xdd"]


def test_clean_strips_own_prefix():
    assert clean_reply("botucha: nu nax", ["Tadas"]) == ["nu nax"]
    assert clean_reply("Botucha: **nu** nax", ["Tadas"]) == ["nu nax"]


def test_clean_caps_three():
    assert len(clean_reply("a\nb\nc\nd\ne", [])) == 3


def test_clean_strips_quotes_and_bullets():
    assert clean_reply('"hodlinam iki nulio"\n- xdd', []) == ["hodlinam iki nulio", "xdd"]


async def test_retry_then_none():
    llm = FakeLLM(["", ""])
    assert await generate_reply(llm, ctx(), num_predict=150, max_chars=10_000, member_names=[]) is None
    assert len(llm.calls) == 2


async def test_retry_after_exception():
    llm = FakeLLM([TimeoutError(), "ok"])
    assert await generate_reply(llm, ctx(), num_predict=150, max_chars=10_000, member_names=[]) == ["ok"]


def test_serious_mode_drops_style_and_instructs_system():
    msgs = build_prompt(ctx(serious=True), max_chars=100_000)
    assert "STYLE" not in msgs[0]["content"]
    assert "RIMTAI" in msgs[0]["content"]


def test_clean_serious_allows_more_lines():
    raw = "\n".join(f"eilute {i}" for i in range(10))
    assert len(clean_reply(raw, [], max_lines=8)) == 8


async def test_serious_uses_bigger_budget():
    llm = FakeLLM(["a\nb\nc\nd\ne"])
    out = await generate_reply(llm, ctx(serious=True), num_predict=150, max_chars=10_000, member_names=[])
    assert len(out) == 5 and llm.calls[0]["num_predict"] >= 400


def test_clean_drops_mangled_member_and_role_labels():
    raw = "Ta das: xdd\nAssistant: labas\nBOT: nu\nhodlinam"
    assert clean_reply(raw, ["Tadas", "mantas"]) == ["hodlinam"]


def test_clean_keeps_normal_colon_text():
    assert clean_reply("taip: 3x leverage", ["Tadas"]) == ["taip: 3x leverage"]


async def test_foreign_script_triggers_retry():
    llm = FakeLLM(["nu v टास्कai i norvegija", "nu i norvegija xdd"])
    out = await generate_reply(llm, ctx(), num_predict=150, max_chars=10_000, member_names=[])
    assert out == ["nu i norvegija xdd"] and len(llm.calls) == 2


async def test_foreign_script_words_removed_after_second_try():
    llm = FakeLLM(["vertė kريسės", "vertė kريسės labai"])
    out = await generate_reply(llm, ctx(), num_predict=150, max_chars=10_000, member_names=[])
    assert out == ["vertė labai"]


def test_lithuanian_cyrillic_emoji_allowed():
    from botucha.brain import has_foreign_script
    assert not has_foreign_script("ąčęėįšųūž xdd 🤡 давай 3x")
    assert has_foreign_script("üçių") and has_foreign_script("टास्क") and has_foreign_script("كريس")


def test_lines_written_as_a_member_are_dropped_by_any_form_of_their_name():
    names = ["Jonas", "jonas_k", "jonka", "Aidas"]
    assert clean_reply("Jonka: pirk viska\nlabas", names) == ["labas"]            # nickname
    assert clean_reply("Jonas Petraitis: pirk viska\nlabas", names) == ["labas"]  # longer than the stored name
    assert clean_reply("Jona: pirk viska\nlabas", names) == ["labas"]             # mangled
    assert clean_reply("AI: as esu dirbtinis intelektas\nlabas", names) == ["labas"]


def test_ordinary_lines_with_a_colon_are_kept():
    names = ["Jonas", "Aidas"]
    assert clean_reply("ai: gerai", names) == ["ai: gerai"]  # an interjection, not the AI label
    assert clean_reply("jo: bus gerai", names) == ["jo: bus gerai"]  # 'yes', not the start of Jonas
    assert clean_reply("kaina: 125 usd", names) == ["kaina: 125 usd"]


async def test_reply_filter_knows_friends_and_nicknames(app):
    from tests.test_app import inc, settle
    bot, store, llm, out = await app(["Petriukas: as tau sakiau\nnu jo"])
    bot.memory.add_person("Petras", ["petriukas"])
    await bot.on_message(inc("botucha ka sake petras"))
    await settle()
    assert [t for _, t, _ in out.sent] == ["nu jo"]


def test_a_short_alias_does_not_swallow_ordinary_words():
    """Review finding: a label that merely starts with a 2-letter alias was taken for that person."""
    names = ["Marius", "ma", "Al"]
    assert clean_reply("manau: brangu", names) == ["manau: brangu"]
    assert clean_reply("alio: kas cia", names) == ["alio: kas cia"]
    assert clean_reply("Ma: pirk viska\nlabas", names) == ["labas"]          # the alias itself still counts
    assert clean_reply("Marius Petraitis: pirk viska\nlabas", names) == ["labas"]  # and a longer form of the name


# --- tics, repeated phrases, length ------------------------------------------------------------------------

from botucha.brain import repeated_phrase, shorten, strip_tics  # noqa: E402

TSG_HISTORY = ["tadas, tsg ne varyk man galvos xddd", "mantas, tsg viskas normalno xddd", "nu jo"]


def test_filler_opener_and_closer_left_out_when_overused():
    out = strip_tics(["tadas, tsg tavo kava baigėsi xddd."], TSG_HISTORY)
    assert out == ["tadas, tavo kava baigėsi"]


def test_filler_kept_when_used_now_and_then():
    assert strip_tics(["tadas, tsg tavo kava baigėsi xddd"], ["nu jo", "mantas, tsg ok"]) == \
        ["tadas, tsg tavo kava baigėsi xddd"]


def test_filler_without_address_and_real_first_words_kept():
    hist = ["tsg, ne varyk xddd", "tsg ne varyk xddd"]
    assert strip_tics(["tsg, ne čia reikalas"], hist) == ["ne čia reikalas"]
    assert strip_tics(["ne čia reikalas"], ["ne varyk", "ne dabar"]) == ["ne čia reikalas"]  # "ne" is no filler


def test_repeated_phrase_found_across_messages():
    hist = ["varyk jau savo baxurą, kol tave nuovargis visai neišjungė xddd"]
    assert repeated_phrase("tsg, kol tave nuovargis visai neišjungė, eik miegot", hist) == \
        "kol tave nuovargis visai neisjunge"
    assert repeated_phrase("eik geriau miegot, čiuvak", hist) == ""


def test_shorten_cuts_at_last_full_sentence():
    long = "pirmas sakinys čia. " + "antras sakinys yra gerokai ilgesnis " * 6 + "ir baigiasi. trečias."
    out = shorten([long], 60)
    assert out == ["pirmas sakinys čia."]
    assert shorten(["trumpas"], 60) == ["trumpas"]
    assert shorten(["vienas labai ilgas sakinys be pabaigos " * 5], 60)[0].startswith("vienas")  # never mid-sentence


async def test_repeated_phrase_regenerates_once():
    llm = FakeLLM(["kol tave nuovargis visai neišjungė, čiuvak", "eik miegot, čiuvak"])
    out = await generate_reply(llm, ctx(), num_predict=150, max_chars=10_000, member_names=[],
                               recent_own=["varyk jau, kol tave nuovargis visai neišjungė"])
    assert out == ["eik miegot, čiuvak"] and len(llm.calls) == 2


async def test_repeated_phrase_twice_still_answers():
    rep = "kol tave nuovargis visai neišjungė, čiuvak"
    llm = FakeLLM([rep, rep])
    out = await generate_reply(llm, ctx(), num_predict=150, max_chars=10_000, member_names=[],
                               recent_own=["varyk jau, kol tave nuovargis visai neišjungė"])
    assert out == [rep]


async def test_long_reply_shortened_but_serious_not():
    long = "pirmas sakinys. " + "x" * 300 + "."
    assert await generate_reply(FakeLLM([long]), ctx(), num_predict=150, max_chars=10_000,
                                member_names=[]) == ["pirmas sakinys."]
    out = await generate_reply(FakeLLM([long]), ctx(serious=True), num_predict=150, max_chars=10_000, member_names=[])
    assert out == [long]


# --- no name in front of a direct reply ---------------------------------------------------------------------

from botucha.brain import strip_address  # noqa: E402

NAMES = ["Tadas", "mantas", "rutele"]


def test_direct_reply_loses_the_name_in_front():
    assert strip_address(["tadas, tsg ne varyk man galvos"], NAMES) == ["tsg ne varyk man galvos"]
    assert strip_address(["@mantas, imsi trečią", "antra eilutė"], NAMES) == ["imsi trečią", "antra eilutė"]
    assert strip_address(["Tadas,"], NAMES) == []


def test_other_first_words_and_names_later_stay():
    assert strip_address(["zdarova, ką skubi?"], NAMES) == ["zdarova, ką skubi?"]
    assert strip_address(["tsg, mantas, ne čia"], NAMES) == ["tsg, mantas, ne čia"]
    assert strip_address(["ne varyk, tadas"], NAMES) == ["ne varyk, tadas"]


async def test_generation_strips_the_name_only_when_called_directly():
    out = await generate_reply(FakeLLM(["tadas, nu jo"]), ctx(), num_predict=150, max_chars=10_000,
                               member_names=["Tadas"])
    assert out == ["nu jo"]
    from botucha.brain import generate_reply_ex
    res = await generate_reply_ex(FakeLLM(["tadas, nu jo"]), ctx(), num_predict=150, max_chars=10_000,
                                  member_names=["Tadas"], direct=False)
    assert res.texts == ["tadas, nu jo"]
