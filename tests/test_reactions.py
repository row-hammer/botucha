"""Reactions that fit the message: the emoji whose example messages are closest in meaning, or none at all."""
import asyncio
from pathlib import Path

import numpy as np
import pytest

from botucha.config import ConfigError, load_config
from botucha.reactions import NO_REACTION, ReactionPicker
from tests.fakes import FakeEmbedder
from tests.test_app import C, app, inc, settle  # noqa: F401  (app is a fixture)

EXAMPLES = {
    "🤣": ["hahaha mirštu iš juoko", "geriausias bajeris šiandien"],
    "💩": ["rinka krenta viskas raudona", "praradau pusę portfelio"],
    "🥴": ["vakar išgėriau per daug alaus", "nemiegojau visą naktį"],
    NO_REACTION: ["kada susitinkam rytoj", "atsiųsk nuorodą vėliau"],
}


class CountingEmbedder(FakeEmbedder):
    def __init__(self, fail=False):
        super().__init__()
        self.texts, self.fail = [], fail

    async def embed(self, texts):
        if self.fail:
            raise ConnectionError("ollama down")
        self.texts += texts
        return await super().embed(texts)


async def test_the_emoji_closest_in_meaning_is_picked():
    p = ReactionPicker(CountingEmbedder(), ["🤣", "💩", "🥴"], EXAMPLES)
    assert await p.pick("xdd mirštu iš juoko") == "🤣"
    assert await p.pick("mano portfelis krenta viskas raudona") == "💩"
    assert await p.pick("per daug alaus vakar") == "🥴"


async def test_no_reaction_when_the_message_is_plain_talk():
    p = ReactionPicker(CountingEmbedder(), ["🤣", "💩", "🥴"], EXAMPLES)
    assert await p.pick("kada susitinkam rytoj?") is None


async def test_only_configured_emojis_with_examples_can_be_picked():
    p = ReactionPicker(CountingEmbedder(), ["🤣", "🗿"], EXAMPLES)  # 🗿 has no examples, 💩 is not configured
    assert await p.pick("rinka krenta viskas raudona") in ("🤣", None)
    assert p.unmatched == ["🗿"]


async def test_examples_are_embedded_once():
    e = CountingEmbedder()
    p = ReactionPicker(e, ["🤣", "💩", "🥴"], EXAMPLES)
    for text in ("hahaha", "krenta", "alaus"):
        await p.pick(text)
    examples = sum(len(v) for v in EXAMPLES.values())
    assert len(e.texts) == examples + 3


async def test_a_failing_embedder_falls_back_to_a_random_configured_emoji():
    p = ReactionPicker(CountingEmbedder(fail=True), ["🤣", "💩"], EXAMPLES, fallback=lambda xs: xs[-1])
    assert await p.pick("bet kas") == "💩"


# ---- in the bot -----------------------------------------------------------------------------------------
async def test_the_bot_reacts_with_the_fitting_emoji(app):
    bot, store, llm, out = await app(rng_value=0.5)
    bot.cfg = bot.cfg.__class__(**{**bot.cfg.__dict__, "trigger": bot.cfg.trigger.__class__(
        **{**bot.cfg.trigger.__dict__, "keyword_prob": 0.0, "random_n": 10**9, "reaction_n": 1})})
    bot.reaction_picker = ReactionPicker(CountingEmbedder(), ["🤣", "💩", "🥴"], EXAMPLES)
    await bot.on_message(inc("hahaha mirštu iš juoko", msg_id=1))
    assert out.reactions == [(C, 1, "🤣")]


async def test_no_fitting_emoji_means_no_reaction_and_no_cooldown_used(app):
    bot, store, llm, out = await app(rng_value=0.5)
    bot.cfg = bot.cfg.__class__(**{**bot.cfg.__dict__, "trigger": bot.cfg.trigger.__class__(
        **{**bot.cfg.trigger.__dict__, "keyword_prob": 0.0, "random_n": 10**9, "reaction_n": 1})})
    bot.reaction_picker = ReactionPicker(CountingEmbedder(), ["🤣", "💩", "🥴"], EXAMPLES)
    await bot.on_message(inc("kada susitinkam rytoj", msg_id=1))
    assert out.reactions == [] and bot.state.last_unsolicited == 0.0
    await bot.on_message(inc("hahaha mirštu iš juoko", msg_id=2))  # the next fitting message still gets one
    assert out.reactions == [(C, 2, "🤣")]


async def test_a_photo_is_judged_by_its_caption(app):
    bot, store, llm, out = await app(rng_value=0.5)
    bot.cfg = bot.cfg.__class__(**{**bot.cfg.__dict__, "trigger": bot.cfg.trigger.__class__(
        **{**bot.cfg.trigger.__dict__, "keyword_prob": 0.0, "random_n": 10**9, "reaction_n": 1})})
    e = CountingEmbedder()
    bot.reaction_picker = ReactionPicker(e, ["🤣", "💩", "🥴"], EXAMPLES)
    await bot.on_message(inc("rinka krenta viskas raudona", msg_id=1, image_file_id="F1"))
    assert out.reactions == [(C, 1, "💩")] and "[nuotrauka] rinka krenta viskas raudona" not in e.texts


# ---- config ----------------------------------------------------------------------------------------------
EX = Path(__file__).parent.parent / "config.example.toml"


def test_examples_can_be_set_per_emoji_in_the_config(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(EX.read_text() + '\n[reaction_examples]\n"🤡" = ["pirkau ant viršaus", "vėl apsijuokiau"]\n')
    cfg = load_config(p, {"BOTUCHA_TOKEN": "t"})
    assert dict(cfg.reaction_examples)["🤡"] == ("pirkau ant viršaus", "vėl apsijuokiau")
    assert load_config(EX, {"BOTUCHA_TOKEN": "t"}).reaction_examples == ()


def test_bad_examples_are_refused(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(EX.read_text() + '\n[reaction_examples]\n"🤡" = "ne sąrašas"\n')
    with pytest.raises(ConfigError, match="reaction_examples"):
        load_config(p, {"BOTUCHA_TOKEN": "t"})
