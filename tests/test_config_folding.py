"""Words from the config are matched the way chat text is: case and Lithuanian letters do not matter."""
import dataclasses
from pathlib import Path

from botucha.config import load_config
from botucha.guard import mentions_bot
from botucha.prices import DEFAULT_ALIASES, detect_symbols
from botucha.trigger import is_direct, matched_keyword
from tests.test_app import app, inc  # noqa: F401  (app is a fixture)

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"


def cfg_with(tmp_path, extra: str, replace: dict[str, str] | None = None):
    text = EXAMPLE.read_text()
    for a, b in (replace or {}).items():
        assert a in text
        text = text.replace(a, b)
    p = tmp_path / "c.toml"
    p.write_text(text + extra)
    return load_config(p, {"BOTUCHA_TOKEN": "t"})


def test_keywords_with_lithuanian_letters_match(tmp_path):
    cfg = cfg_with(tmp_path, "", {'keywords = ["spx",': 'keywords = ["Šort", "spx",'})
    assert "sort" in cfg.trigger.keywords
    assert matched_keyword("šortinu viską", cfg.trigger.keywords) == "sort"


def test_price_aliases_with_lithuanian_letters_match(tmp_path):
    cfg = cfg_with(tmp_path, "", {"# aliases = {": 'aliases = { "Žaliav" = "GC=F" }\n# aliases = {'})
    aliases = {**DEFAULT_ALIASES, **dict(cfg.prices.aliases)}
    assert detect_symbols("pirkau žaliavų", aliases) == ["GC=F"]


def test_the_bot_name_pattern_ignores_case_and_lithuanian_letters(tmp_path):
    cfg = cfg_with(tmp_path, "", {'bot_name_regex = "botuch\\\\w*"': 'bot_name_regex = "Botuch\\\\w*|Ąžuoliuk\\\\w*"'})
    for text in ("ąžuoliuk, ka manai", "BOTUCHA ka manai"):
        assert is_direct(text, reply_to_bot=False, mentions_bot=False, name_regex=cfg.telegram.bot_name_regex), text
        assert mentions_bot(text, cfg.telegram.bot_name_regex), text


async def test_nerimtai_is_not_serious_mode(app):
    bot, *_ = await app()
    jobs = []
    bot.worker.submit = jobs.append
    await bot.on_message(inc("botucha tu cia nerimtai sneki", msg_id=1))
    await bot.on_message(inc("botucha rimtai, kas yra etf?", msg_id=2))
    await bot.on_message(inc("botucha, Rimtai: kas yra etf", msg_id=3))
    assert [j.serious for j in jobs] == [False, True, True]
