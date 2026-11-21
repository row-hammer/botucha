"""Prompt layout for the model's cache: the system message is the same from reply to reply, everything that
changes comes after the transcript, and the stable block is sent once on its own so the engine keeps it.
Measured on the real model: 15.7 s of prompt reading per reply before, about 5.3 s with this layout."""
import dataclasses

from botucha.brain import MEMORY_GUARD, REPLY_INSTRUCTION, PromptContext, build_prompt, prompt_sections, stable_prompt
from botucha.llm import ChatResult
from botucha.store import StoredMessage
from tests.test_app import BOT_ID, C, app, inc, settle  # noqa: F401  (app is a fixture)


def ctx(**kw):
    base = dict(persona="PERSONA", style_examples="STYLE", profiles={"Tadas": "PROFILE"}, slang=["zjbs = gerai"],
                chunks=["CHUNK"], facts=["FACT"], history=[StoredMessage(C, 1, 111, "Tadas", 1.0, "ka manai")],
                bot_user_id=BOT_ID, prices=["NVDA 1"], people=["Jonas: SOMEONE"], spelling_notes=["a (ne b)"])
    return PromptContext(**{**base, **kw})


def test_system_message_holds_only_what_stays_the_same():
    system, user = (m["content"] for m in build_prompt(ctx(), max_chars=100_000))
    for stable in ("PERSONA", "STYLE", "PROFILE", "zjbs", "a (ne b)"):
        assert stable in system and stable not in user
    for changing in ("CHUNK", "FACT", "SOMEONE", "NVDA 1"):
        assert changing in user and changing not in system
    assert system == stable_prompt(ctx())


def test_system_message_does_not_change_with_the_conversation():
    a = build_prompt(ctx(), max_chars=100_000)[0]["content"]
    b = build_prompt(ctx(chunks=["OTHER"], facts=[], prices=[], people=["Ona: x"], image=b"png",
                         history=[StoredMessage(C, 9, 222, "Mantas", 9.0, "visai kas kita")]), max_chars=100_000)[0]["content"]
    assert a == b


def test_memory_comes_after_the_transcript_marked_as_data_and_before_the_instruction():
    user = build_prompt(ctx(), max_chars=100_000)[1]["content"]
    order = [user.index(s) for s in ("Tadas: ka manai", MEMORY_GUARD, "SOMEONE", "CHUNK", "FACT", "NVDA 1", REPLY_INSTRUCTION)]
    assert order == sorted(order) and user.rstrip().endswith(REPLY_INSTRUCTION)


def test_no_memory_no_guard_line():
    user = build_prompt(ctx(chunks=[], facts=[], prices=[], people=[]), max_chars=100_000)[1]["content"]
    assert MEMORY_GUARD not in user


def test_history_budget_counts_the_memory_block():
    hist = [StoredMessage(C, i, 111, "Tadas", float(i), f"m{i:02d} " + "x" * 500) for i in range(40)]
    msgs = build_prompt(ctx(history=hist, chunks=["C" * 1500]), max_chars=4000)
    assert sum(len(m["content"]) for m in msgs) <= 4000 and "m39" in msgs[1]["content"] and "C" * 1500 in msgs[1]["content"]


def test_sections_still_listed_for_the_dashboard():
    assert list(prompt_sections(ctx())) == ["persona", "guard", "price_rule", "style", "spelling", "profiles", "slang",
                                            "people", "chunks", "facts", "prices"]


class TimedLLM:
    """Every call recorded; the reply's stats say how slowly the prompt was read."""

    def __init__(self, ms_per_token=0.2):
        self.calls, self.ms_per_token = [], ms_per_token

    async def chat_ex(self, messages, *, num_predict, fmt_json=False, images=None):
        self.calls.append({"messages": messages, "num_predict": num_predict})
        return ChatResult("labas", {"prompt_eval_count": 1000, "prompt_eval_ms": 1000 * self.ms_per_token})

    async def chat(self, messages, *, num_predict, fmt_json=False):
        return (await self.chat_ex(messages, num_predict=num_predict)).text


def warmups(llm):
    return [c for c in llm.calls if c["num_predict"] == 1]


async def test_no_warm_up_unless_switched_on(app):
    bot, _, llm, _ = await app(["labas"])
    assert await bot.warm_prompt() is False
    await bot.on_message(inc("botucha labas"))
    await settle()
    assert len(llm.calls) == 1


async def test_warm_up_sends_exactly_the_system_message_of_the_next_reply(app):
    bot, _, _, _ = await app()
    bot.llm, bot.warm_prompt_cache = TimedLLM(), True

    assert await bot.warm_prompt() is True
    assert await bot.warm_prompt() is False  # nothing changed: not sent again
    await bot.on_message(inc("botucha labas"))
    await settle()

    [warm] = warmups(bot.llm)
    reply = next(c for c in bot.llm.calls if c["num_predict"] != 1)
    assert warm["messages"][0] == reply["messages"][0] and warm["messages"][0]["role"] == "system"


async def test_warm_up_again_when_the_stable_block_changes(app):
    bot, _, _, _ = await app()
    bot.llm, bot.warm_prompt_cache = TimedLLM(), True
    await bot.warm_prompt()
    bot.cfg.paths.persona.write_text("tu esi botucha, bet kitoks")
    await bot.on_message(inc("botucha labas"))
    await settle()
    assert len(warmups(bot.llm)) == 2 and "kitoks" in warmups(bot.llm)[-1]["messages"][0]["content"]


async def test_a_slowly_read_prompt_means_the_cache_was_lost_so_it_is_warmed_again(app):
    bot, _, _, _ = await app()
    bot.llm, bot.warm_prompt_cache = TimedLLM(ms_per_token=2.0), True  # 2 ms per token: read from scratch
    await bot.warm_prompt()
    await bot.on_message(inc("botucha labas"))
    await settle()
    assert len(warmups(bot.llm)) == 2
    bot.llm.ms_per_token = 0.2  # read from the cache: nothing to repair
    await bot.on_message(inc("botucha dar karta", msg_id=2))
    await settle()
    assert len(warmups(bot.llm)) == 2


async def test_a_failed_warm_up_never_breaks_anything(app):
    bot, _, _, out = await app(["labas"])
    bot.warm_prompt_cache = True

    class Down(TimedLLM):
        async def chat_ex(self, messages, *, num_predict, fmt_json=False, images=None):
            if num_predict == 1:
                raise ConnectionError("ollama down")
            return await super().chat_ex(messages, num_predict=num_predict)
    bot.llm = Down()
    assert await bot.warm_prompt() is False
    await bot.on_message(inc("botucha labas"))
    await settle()
    assert out.sent[-1][1] == "labas"


async def test_warmed_again_after_a_learning_run_used_the_model(app):
    bot, store, _, _ = await app()
    bot.llm, bot.warm_prompt_cache = TimedLLM(), True
    await bot.warm_prompt()
    for i in range(40):
        store.add_message(StoredMessage(C, i + 1, 111, "Tadas", i * 4000.0, f"pokalbis {i} apie akcijas"))
    bot.clock = lambda: 1e12
    bot.llm.chat_ex_json = '{"facts": [], "slang": []}'

    async def chat_ex(messages, *, num_predict, fmt_json=False, images=None):
        bot.llm.calls.append({"messages": messages, "num_predict": num_predict})
        return ChatResult('{"facts": [], "slang": []}' if fmt_json else "profilis", {})
    bot.llm.chat_ex = chat_ex

    await bot.learn_tick()

    assert len(warmups(bot.llm)) == 2 and bot.llm.calls[-1]["num_predict"] == 1  # last thing it did


async def test_not_warmed_again_after_an_idle_tick_that_did_nothing(app):
    bot, _, _, _ = await app()
    bot.llm, bot.warm_prompt_cache = TimedLLM(), True
    await bot.warm_prompt()
    await bot.learn_tick()
    assert len(warmups(bot.llm)) == 1
