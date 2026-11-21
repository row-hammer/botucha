"""Learning reads a backlog in bounded pieces, always moves on, and makes way for a reply."""
import json
import re

from botucha.learn import LEARN_BATCH_CHARS, LEARN_MAX_CALLS, learn_once
from botucha.llm import ChatResult
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder
from tests.test_app import C, app  # noqa: F401  (app is a fixture)

EMPTY = '{"facts": [], "slang": []}'
TRUNCATED = '{"facts": [{"about": "Tadas", "text": "Tadas perka nvidia"}, {"about": "Man'  # cut off at the token limit


def backlog(n, store=None):
    """n conversations an hour apart: one chunk each, about 500 characters."""
    s = store or Store(":memory:")
    for i in range(n):
        s.add_message(StoredMessage(C, i + 1, 111, "Tadas", i * 4000.0, f"pokalbis{i} " + "apie akcijas ir rinka " * 22))
    return s, Memory(s, FakeEmbedder(), clock=lambda: 1e9)


class ScriptedLLM:
    """answer(user text) decides each reply; every call is recorded."""

    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    async def chat_ex(self, messages, *, num_predict, fmt_json=False, images=None):
        self.prompts.append(messages[-1]["content"])
        return ChatResult(self.answer(messages[-1]["content"]), {})

    async def chat(self, messages, *, num_predict, fmt_json=False):
        return (await self.chat_ex(messages, num_predict=num_predict, fmt_json=fmt_json)).text


def cursor(store):
    return int(store.get_state(f"learn_cursor:{C}", "0"))


def last_chunk(store):
    return store.conn.execute("SELECT MAX(id) FROM chunks").fetchone()[0]


async def test_a_backlog_is_read_in_bounded_prompts():
    s, mem = backlog(40)
    await mem.index_new_chunks(C, force=True)
    llm = ScriptedLLM(lambda _: EMPTY)

    await learn_once(mem, llm, C)

    assert len(llm.prompts) > 1 and all(len(p) <= LEARN_BATCH_CHARS for p in llm.prompts)
    seen = re.findall(r"pokalbis\d+", " ".join(llm.prompts))
    assert sorted(seen) == sorted(f"pokalbis{i}" for i in range(40))  # every conversation read exactly once
    assert cursor(s) == last_chunk(s)


async def test_an_answer_that_was_cut_off_is_asked_again_in_smaller_pieces():
    s, mem = backlog(12)
    await mem.index_new_chunks(C, force=True)

    def answer(text):
        if "\n---\n" in text:  # several conversations at once: too many facts to fit the answer
            return TRUNCATED
        return json.dumps({"facts": [{"about": None, "text": f"Tadas kalbejo apie {text.split()[1]}"}], "slang": []})
    llm = ScriptedLLM(answer)

    n = await learn_once(mem, llm, C)

    assert n == 12 and len(mem.all_facts()) == 12  # nothing lost, nothing learned twice
    assert cursor(s) == last_chunk(s)


async def test_a_conversation_the_model_cannot_read_is_tried_twice_and_then_skipped():
    s, mem = backlog(3)
    await mem.index_new_chunks(C, force=True)
    bad = ScriptedLLM(lambda _: "not json")

    assert await learn_once(mem, bad, C) == 0
    assert cursor(s) == 0  # one bad answer: the next run tries again
    runs = 1
    while cursor(s) < last_chunk(s):
        await learn_once(mem, bad, C)
        runs += 1
        assert runs <= 6, "learning is stuck"
    assert mem.all_facts() == []
    assert await learn_once(mem, ScriptedLLM(lambda _: EMPTY), C) == 0  # and nothing is read again


async def test_learning_stops_between_pieces_when_a_reply_is_waiting():
    s, mem = backlog(40)
    await mem.index_new_chunks(C, force=True)
    llm = ScriptedLLM(lambda _: EMPTY)

    await learn_once(mem, llm, C, should_stop=lambda: True)

    assert len(llm.prompts) == 1
    assert 0 < cursor(s) < last_chunk(s)
    await learn_once(mem, llm, C)  # later: goes on where it stopped
    seen = re.findall(r"pokalbis\d+", " ".join(llm.prompts))
    assert sorted(seen) == sorted(f"pokalbis{i}" for i in range(40)) and cursor(s) == last_chunk(s)


async def test_one_run_makes_a_limited_number_of_calls():
    s, mem = backlog(40)
    await mem.index_new_chunks(C, force=True)
    llm = ScriptedLLM(lambda _: EMPTY)
    await learn_once(mem, llm, C, max_calls=2)
    assert len(llm.prompts) == 2 and 0 < cursor(s) < last_chunk(s)


async def test_idle_learning_works_through_a_backlog_over_several_ticks(app):
    bot, store, _, _ = await app()
    backlog(120, store)
    bot.llm = ScriptedLLM(lambda _: EMPTY)
    bot.clock = lambda: 1e12  # everything looks idle and old

    await bot.learn_tick()

    assert len(bot.llm.prompts) == LEARN_MAX_CALLS  # one tick is bounded
    assert 0 < cursor(store) < last_chunk(store)
    assert store.get_state(f"learned_rowid:{C}") is None  # not done: the next tick must go on
    for _ in range(10):
        await bot.learn_tick()
    assert cursor(store) == last_chunk(store)
    assert store.get_state(f"learned_rowid:{C}") == str(store.last_rowid(C))


async def test_bootstrap_reads_the_whole_import_even_past_a_bad_answer(app, monkeypatch):
    from pathlib import Path
    import botucha.learn as learn
    monkeypatch.setattr(learn, "LEARN_BATCH_CHARS", 1)  # one conversation per call
    export = Path(__file__).parent / "fixtures" / "export_small.json"
    bot, store, _, _ = await app(export=export)
    answers = iter(["not json", "not json"])
    bot.llm = ScriptedLLM(lambda _: next(answers, EMPTY))

    await bot.bootstrap()

    assert cursor(store) == last_chunk(store) and last_chunk(store) >= 1
    assert store.get_state("export_imported") == "1"


async def test_profiles_are_refreshed_even_while_a_backlog_is_still_being_read(app):
    """Review finding: an unfinished backlog skipped the profile refresh every tick, so profiles went stale."""
    bot, store, _, _ = await app()
    store.upsert_member(111, "Tadas", "tadas")
    backlog(250, store)  # more than one tick can read, and past the 200-message profile interval
    bot.llm = ScriptedLLM(lambda text: EMPTY if text.startswith("pokalbis") or "\n---\n" in text else EMPTY)

    async def chat(messages, *, num_predict, fmt_json=False):
        return "Tadas kalba apie akcijas." if not fmt_json else EMPTY
    bot.llm.chat = chat
    bot.clock = lambda: 1e12

    await bot.learn_tick()

    assert 0 < cursor(store) < last_chunk(store)  # the backlog is not done
    assert bot.memory.profiles().get(111) == "Tadas kalba apie akcijas."
