"""What the trace needs from the pipeline: model stats, trigger reasons, prompt sizes, search scores."""
from pathlib import Path

import pytest

from botucha.brain import PromptContext, build_prompt, prompt_sections
from botucha.config import load_config
from botucha.llm import ChatResult, OllamaLLM, chat_ex
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from botucha.trigger import Decision, TriggerState, decide_with_reason
from tests.fakes import FakeEmbedder

CFG = load_config(Path(__file__).parent.parent / "config.example.toml", {"BOTUCHA_TOKEN": "t"}).trigger


class Rng:
    def __init__(self, v):
        self.v = v

    def random(self):
        return self.v


def _decide(text, *, direct=False, rng=0.0, state=None):
    return decide_with_reason(text, sender_is_bot=False, direct=direct, started_at=0, msg_ts=10, now=10_000,
                              state=state or TriggerState(), cfg=CFG, rng=Rng(rng))


def test_decide_reason_keyword_random_direct():
    assert _decide("labas", direct=True) == (Decision.REPLY, "direct")
    assert _decide("spx krenta") == (Decision.REPLY, "keyword:spx")
    assert _decide("labas rytas") == (Decision.REPLY, "random:1/25")
    assert _decide("labas", direct=True, state=TriggerState(enabled=False)) == (Decision.NONE, "")


def test_prompt_sections_match_system_text():
    ctx = PromptContext(persona="P" * 10, style_examples="S", profiles={"A": "x"}, slang=["a = b"], chunks=["C"],
                        facts=["F"], history=[StoredMessage(-1, 1, 5, "Tadas", 0.0, "labas")], bot_user_id=1,
                        people=["Jonas: x"], prices=["NVDA 1"])
    sections = prompt_sections(ctx)
    system = build_prompt(ctx, max_chars=10**6)[0]["content"]
    assert sum(sections.values()) + 2 * (len(sections) - 1) == len(system)
    assert list(sections)[:4] == ["persona", "guard", "price_rule", "style"]
    assert list(sections)[-1] == "prices"


async def test_search_facts_scored_flags_fts():
    m = Memory(Store(":memory:"), FakeEmbedder(), clock=lambda: 1.0)
    await m.add_fact("fact", "tadas perka nvidia akcijas", None, "auto")
    await m.add_fact("fact", "jonas kepa kukulius", None, "auto")
    hits = await m.search_facts_scored("nvidia", k=5)
    by_text = {f.text: (score, fts) for f, score, fts in hits}
    score, fts = by_text["tadas perka nvidia akcijas"]
    assert fts is True and -1.0 <= score <= 1.0
    assert [f.text for f in await m.search_facts("nvidia", k=5)] == [f.text for f, _, _ in hits]


async def test_chat_ex_wraps_plain_llm():
    class Plain:
        async def chat(self, messages, *, num_predict, fmt_json=False):
            return "x"
    assert await chat_ex(Plain(), [], num_predict=5) == ChatResult("x", {})


def test_ollama_stats_from_response():
    s = OllamaLLM._stats({"model": "m", "eval_count": 80, "eval_duration": 10_000_000_000, "prompt_eval_count": 900,
                          "prompt_eval_duration": 2e9, "load_duration": 0, "total_duration": 12e9})
    assert s["tok_s"] == pytest.approx(8.0) and s["eval_ms"] == pytest.approx(10_000.0)
    assert s["prompt_eval_count"] == 900 and s["load_ms"] == 0 and s["total_ms"] == pytest.approx(12_000.0)
    assert OllamaLLM._stats({"eval_count": 0, "eval_duration": 0})["tok_s"] is None
