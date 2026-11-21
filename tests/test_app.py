import asyncio
import dataclasses
import random
from pathlib import Path

import pytest

from botucha.app import CANNED, Botucha, Incoming
from botucha.config import load_config
from botucha.memory import Memory
from botucha.store import Store
from tests.fakes import FakeEmbedder, FakeLLM

ROOT = Path(__file__).parent.parent
FIX = Path(__file__).parent / "fixtures" / "export_small.json"
BOT_ID = 999
C = -1001234567890


class FakeOutbox:
    def __init__(self):
        self.sent: list[tuple[int, str, int | None]] = []
        self.reactions: list[tuple[int, int, str]] = []
        self.typing_calls = 0
        self.left: list[int] = []
        self._next = 5000
        self.images: dict[str, bytes] = {}
        self.fetched: list[str] = []

    async def send(self, chat_id, texts, reply_to):
        ids = []
        for t in texts:
            self.sent.append((chat_id, t, reply_to))
            self._next += 1
            ids.append(self._next)
        return ids

    async def react(self, chat_id, msg_id, emoji):
        self.reactions.append((chat_id, msg_id, emoji))

    async def typing(self, chat_id):
        self.typing_calls += 1

    async def leave(self, chat_id):
        self.left.append(chat_id)

    async def fetch_image(self, file_id):
        self.fetched.append(file_id)
        if file_id not in self.images:
            raise RuntimeError(f"no such file {file_id}")
        return self.images[file_id]


async def nosleep(_):
    return None


def make_cfg(tmp_path, export=None):
    cfg = load_config(ROOT / "config.example.toml", {"BOTUCHA_TOKEN": "t"})
    (tmp_path / "persona.md").write_text("tu esi botucha")
    (tmp_path / "style.txt").write_text("mantas: nua na xdd")
    paths = dataclasses.replace(cfg.paths, persona=tmp_path / "persona.md",
                                style_examples=tmp_path / "style.txt", export=export)
    trig = dataclasses.replace(cfg.trigger, burst_quiet_s=0.01, burst_max_s=0.05)
    tele = dataclasses.replace(cfg.telegram, chat_ids=(C,))
    return dataclasses.replace(cfg, paths=paths, trigger=trig, telegram=tele)


@pytest.fixture
async def app(tmp_path):
    made = {}

    async def factory(responses=(), export=None, rng_value=0.99):
        cfg = make_cfg(tmp_path, export)
        store = Store(":memory:")
        mem = Memory(store, FakeEmbedder(), clock=lambda: 10_000.0)
        llm, out = FakeLLM(list(responses)), FakeOutbox()
        rng = random.Random(0)
        rng.random = lambda: rng_value
        bot = Botucha(cfg, store, mem, llm, out, rng=rng, clock=lambda: 10_000.0,
                      bot_user_id=BOT_ID, bot_username="botucha_bot", sleep=nosleep, started_at=1_000.0)
        made["task"] = asyncio.create_task(bot.worker.run())
        made["bot"] = bot
        return bot, store, llm, out

    yield factory
    if "bot" in made:
        await made["bot"].worker.stop()
        made["task"].cancel()


def inc(text, msg_id=1, chat=C, user=111, **kw):
    base = dict(chat_id=chat, msg_id=msg_id, user_id=user, name="Tadas", username="tadas", is_bot=False,
                ts=9_000.0, text=text, reply_to=None, reply_to_bot=False, mentions_bot=False, edited=False)
    return Incoming(**{**base, **kw})


async def settle():
    await asyncio.sleep(0.15)


async def test_foreign_chat_ignored(app):
    bot, store, _, out = await app()
    await bot.on_message(inc("botucha", chat=-5))
    assert store.recent_messages(-5, 5) == [] and out.sent == []


async def test_direct_message_gets_reply(app):
    bot, store, llm, out = await app(["Tadas: ne\nhodlinam iki nulio\nxdd"])
    await bot.on_message(inc("botucha ka daryt su spx"))
    await settle()
    assert [t for _, t, _ in out.sent] == ["hodlinam iki nulio", "xdd"]
    assert out.sent[0][2] == 1  # first message replies to the caller
    last = store.recent_messages(C, 1)[0]
    assert last.is_bot and last.user_id == BOT_ID and last.text == "xdd"


async def test_llm_failure_direct_sends_canned(app):
    bot, _, _, out = await app([RuntimeError("down"), RuntimeError("down")])
    await bot.on_message(inc("botucha?"))
    await settle()
    assert [t for _, t, _ in out.sent] == [CANNED]
    assert bot.last_error


async def test_llm_failure_unsolicited_silent(app):
    bot, _, _, out = await app(["", ""], rng_value=0.0)  # rng 0 -> keyword reply fires
    await bot.on_message(inc("spx krenta"))
    await settle()
    assert out.sent == []


async def test_edit_updates_no_reply(app):
    bot, store, _, out = await app(["x"])
    await bot.on_message(inc("senas", msg_id=7))
    await bot.on_message(inc("botucha naujas", msg_id=7, edited=True))
    await settle()
    assert store.recent_messages(C, 1)[0].text == "botucha naujas"
    assert out.sent == []


async def test_empty_media_message_stored_no_reply(app):
    bot, store, _, out = await app(["x"], rng_value=0.0)
    await bot.on_message(inc("", mentions_bot=True))
    await settle()
    assert len(store.recent_messages(C, 5)) == 1 and out.sent == [] and out.reactions == []


async def test_own_message_no_loop(app):
    bot, _, llm, out = await app(["x"])
    await bot.on_message(inc("botucha hodlinam", user=BOT_ID, is_bot=True, name="Botucha"))
    await settle()
    assert out.sent == [] and llm.calls == []


async def test_command_reply(app):
    bot, _, llm, out = await app()
    await bot.on_message(inc("/isimink tomas veluoja"))
    assert out.sent[0][1].startswith("isiminiau")
    assert llm.calls == []


async def test_react_uses_configured_emoji(app):
    bot, _, _, out = await app(rng_value=0.05)  # no reply, but reaction fires
    await bot.on_message(inc("nu jo"))
    assert out.reactions and out.reactions[0][2] in bot.cfg.trigger.reactions


async def test_old_message_not_answered(app):
    bot, _, _, out = await app(["x"])
    await bot.on_message(inc("botucha", ts=10.0))
    await settle()
    assert out.sent == []


async def test_bootstrap_runs_once(app):
    bot, store, llm, _ = await app(['{"facts": [], "slang": []}', "p1", "p2", "p3"], export=FIX)
    await bot.bootstrap()
    n = len(store.recent_messages(C, 100))
    assert n == 5
    await bot.bootstrap()
    assert len(store.recent_messages(C, 100)) == n
    assert store.get_state("export_imported") == "1"


async def test_atsimeni_sends_links(app):
    bot, store, _, out = await app(["atsimenu, buvo bajeris"])
    for i, (ts, text) in enumerate([(0.0, "daway uzshortinam vwce"), (4000.0, "sefas uzknisa")]):
        await bot.on_message(inc(text, msg_id=100 + i, ts=ts))
    await bot.memory.index_new_chunks(C, force=True)
    await bot.on_message(inc("/atsimeni kai shortinom vwce", msg_id=200))
    await settle()
    assert out.sent[-1][1].startswith("https://t.me/c/1234567890/")


async def test_foreign_chat_logged_once(app, caplog):
    bot, *_ = await app()
    caplog.set_level("INFO", logger="botucha.app")
    await bot.on_message(inc("x", chat=-42))
    await bot.on_message(inc("y", chat=-42, msg_id=2))
    hits = [r for r in caplog.records if "ignoring chat -42" in r.getMessage()]
    assert len(hits) == 1


async def test_private_chat_always_direct(app):
    bot, _, _, out = await app(["labas tau"])
    dm = 100000001
    bot.cfg = dataclasses.replace(bot.cfg, telegram=dataclasses.replace(bot.cfg.telegram, chat_ids=(C, dm)))
    await bot.on_message(inc("labas", chat=dm, user=dm))
    await settle()
    assert [t for _, t, _ in out.sent] == ["labas tau"]
