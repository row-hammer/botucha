"""The model is told which message it answers: the one he replies to in Telegram, not just "the latest"."""
from botucha.brain import REPLY_INSTRUCTION, TARGET_LINE, PromptContext, build_prompt
from botucha.store import StoredMessage
from tests.test_app import BOT_ID, C, app, inc, settle  # noqa: F401  (app is a fixture)


def m(i, text, name="Mantas", user=222):
    return StoredMessage(C, i, user, name, float(i), text)


def ctx(history, targets):
    return PromptContext("P", "S", {}, [], [], [], history, BOT_ID, targets=targets)


def test_the_answered_message_is_named_right_before_the_instruction():
    ask = m(1, "botucha ar verta pirkti nvidia", "Tadas", 111)
    hist = [ask, *[m(2 + i, f"visai kita tema {i}") for i in range(5)]]
    user = build_prompt(ctx(hist, [ask]), max_chars=100_000)[1]["content"]
    tail = user[user.index(TARGET_LINE):]
    assert "Tadas: botucha ar verta pirkti nvidia" in tail and tail.rstrip().endswith(REPLY_INSTRUCTION)
    assert "visai kita tema" not in tail


def test_no_target_line_when_he_answers_the_last_message_anyway():
    hist = [m(1, "labas"), m(2, "botucha ka manai", "Tadas", 111)]
    user = build_prompt(ctx(hist, [hist[-1]]), max_chars=100_000)[1]["content"]
    assert TARGET_LINE not in user


def test_an_answered_message_older_than_the_transcript_is_still_shown():
    ask = m(1, "botucha kas yra etf", "Tadas", 111)
    hist = [m(100 + i, f"zinute {i} " + "x" * 400) for i in range(40)]  # the question scrolled out
    msgs = build_prompt(ctx(hist, [ask]), max_chars=6000)
    assert "Tadas: botucha kas yra etf" in msgs[1]["content"] and sum(len(x["content"]) for x in msgs) <= 6000


def test_a_long_target_is_cut_short():
    ask = m(1, "botucha " + "labai ilgas klausimas " * 100, "Tadas", 111)
    user = build_prompt(ctx([ask, m(2, "kita")], [ask]), max_chars=100_000)[1]["content"]
    assert len(user[user.index(TARGET_LINE):]) < 500


async def test_a_queued_mention_is_named_as_the_target(app):
    bot, store, llm, _ = await app(["nu nezinau"])
    await bot.on_message(inc("botucha ar verta pirkti nvidia", msg_id=1))
    for i in range(3):
        await bot.on_message(inc(f"visai kita tema {i}", msg_id=2 + i, user=222, name="Mantas", username="mantas"))
    await settle()
    user = llm.calls[-1]["messages"][1]["content"]
    assert "Tadas: botucha ar verta pirkti nvidia" in user[user.index(TARGET_LINE):]
