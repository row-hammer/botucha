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
    system = build_prompt(ctx(), max_chars=100_000)[0]["content"]
    idx = [system.index(s) for s in ("PERSONA", "STYLE", "PROFILE", "zjbs", "CHUNK", "FACT")]
    assert idx == sorted(idx)


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
