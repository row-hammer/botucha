import time
from pathlib import Path

import pytest

from botucha.commands import TYLA_USED, CommandContext, handle_command, load_trigger_state, message_link, parse_command
from botucha.config import load_config
from botucha.memory import Memory
from botucha.store import Store
from botucha.trigger import TriggerState
from tests.fakes import FakeEmbedder

CFG = load_config(Path(__file__).parent.parent / "config.example.toml", {"BOTUCHA_TOKEN": "t"})
ADMIN = CFG.telegram.admin_id
MEMBER = 111
C = -1001234567890


@pytest.fixture
def ctx():
    s = Store(":memory:")
    s.upsert_member(MEMBER, "Tadas", "tadas")
    return CommandContext(memory=Memory(s, FakeEmbedder(), clock=lambda: 50.0), store=s,
                          state=TriggerState(), cfg=CFG, started_at=0.0, last_error=None, chat_id=C)


async def run(ctx, text, sender=MEMBER, now=100.0):
    name, args = parse_command(text, "botucha_bot")
    return await handle_command(name, args, sender, now, ctx)


def test_parse_with_botname():
    assert parse_command("/Isimink@botucha_bot tomas veluoja", "botucha_bot") == ("isimink", "tomas veluoja")
    assert parse_command("/tyla", "botucha_bot") == ("tyla", "")
    assert parse_command("/tyla@kitas_bot 5", "botucha_bot") is None
    assert parse_command("nu jo", "botucha_bot") is None


async def test_isimink_adds_fact(ctx):
    reply = await run(ctx, "/isimink tomas visada veluoja")
    assert reply.startswith("isiminiau (#")
    assert ctx.memory.facts_about(None)[0].source == f"cmd:{MEMBER}"


async def test_slengas(ctx):
    assert (await run(ctx, "/slengas zjbs = zajebys")).startswith("ok, zjbs = zajebys")
    assert "slengas" in (await run(ctx, "/slengas be lygybes"))


async def test_ka_zinai_lists_ids(ctx):
    fid = await ctx.memory.add_fact("fact", "tadas turi coreweave", MEMBER, "auto")
    ctx.memory.set_profile(MEMBER, "degenas")
    reply = await run(ctx, "/ka_zinai @tadas", sender=ADMIN)
    assert f"#{fid} tadas turi coreweave" in reply and "degenas" in reply
    assert f"#{fid}" in await run(ctx, "/ka_zinai")  # own when no arg


async def test_admin_only_rejected_for_member(ctx):
    for cmd in ("/pamirsk 1", "/taisyk 1 x", "/daznis 5", "/isjunk", "/ijunk", "/statusas"):
        assert await run(ctx, cmd) == "tik bosas gali"


async def test_pamirsk_deletes(ctx):
    fid = await ctx.memory.add_fact("fact", "x", None, "auto")
    await run(ctx, f"/pamirsk {fid}", sender=ADMIN)
    assert ctx.memory.all_facts() == []
    assert "nera" in await run(ctx, "/pamirsk 999", sender=ADMIN)


async def test_taisyk_updates(ctx):
    fid = await ctx.memory.add_fact("fact", "tadas turi coreweave", MEMBER, "auto")
    await run(ctx, f"/taisyk {fid} tadas turi nvidia", sender=ADMIN)
    assert ctx.memory.facts_about(MEMBER)[0].text == "tadas turi nvidia"


async def test_daznis_persists(ctx):
    await run(ctx, "/daznis 10", sender=ADMIN)
    assert ctx.state.random_n == 10
    assert load_trigger_state(ctx.store, CFG.trigger).random_n == 10
    assert "daznis" in await run(ctx, "/daznis 1", sender=ADMIN)


async def test_isjunk_persists(ctx):
    await run(ctx, "/isjunk", sender=ADMIN)
    assert load_trigger_state(ctx.store, CFG.trigger).enabled is False
    await run(ctx, "/ijunk", sender=ADMIN)
    assert load_trigger_state(ctx.store, CFG.trigger).enabled is True


async def test_tyla_default_60(ctx):
    await run(ctx, "/tyla", sender=ADMIN, now=100.0)
    assert ctx.state.quiet_until == 100.0 + 3600
    await run(ctx, "/tyla 5", sender=ADMIN, now=100.0)
    assert ctx.state.quiet_until == 100.0 + 300


async def test_tyla_once_a_day_for_members(ctx):
    noon = time.mktime((2026, 11, 26, 12, 0, 0, 0, 0, -1))
    assert await run(ctx, "/tyla 10", now=noon) == "ok, tyliu 10 min"
    assert await run(ctx, "/tyla 10", now=noon + 3600) == TYLA_USED
    assert ctx.state.quiet_until == noon + 600  # the second one changed nothing
    assert await run(ctx, "/tyla 10", sender=222, now=noon + 3600) == "ok, tyliu 10 min"  # another member still can
    tomorrow = time.mktime((2026, 11, 27, 0, 5, 0, 0, 0, -1))
    assert await run(ctx, "/tyla 10", now=tomorrow) == "ok, tyliu 10 min"


async def test_tyla_bad_usage_does_not_spend_the_day(ctx):
    assert (await run(ctx, "/tyla x")).startswith("naudok")
    assert (await run(ctx, "/tyla 5256000")).startswith("daugiausia")
    assert await run(ctx, "/tyla 5") == "ok, tyliu 5 min"


async def test_tyla_unlimited_for_admin(ctx):
    for i in range(5):
        assert await run(ctx, "/tyla 5", sender=ADMIN, now=100.0 + i) == "ok, tyliu 5 min"


async def test_statusas(ctx):
    reply = await run(ctx, "/statusas", sender=ADMIN, now=3700.0)
    assert CFG.model.chat_model in reply and "zinuciu" in reply


async def test_unknown_returns_none(ctx):
    assert await run(ctx, "/kazkas") is None
    assert await run(ctx, "/rimtai ka daryt") is None


def test_message_link():
    assert message_link(-1001234567890, 54863) == "https://t.me/c/1234567890/54863"


async def test_tyla_is_capped_at_a_week(ctx):
    from botucha.commands import MAX_TYLA_MIN
    reply = await run(ctx, "/tyla 5256000", now=1000.0)  # ten years
    assert ctx.state.quiet_until == 0.0 and str(MAX_TYLA_MIN) in reply
    await run(ctx, f"/tyla {MAX_TYLA_MIN}", now=1000.0)
    assert ctx.state.quiet_until == 1000.0 + MAX_TYLA_MIN * 60


def test_message_links_exist_only_in_supergroups():
    assert message_link(-1001234567890, 5) == "https://t.me/c/1234567890/5"
    assert message_link(4242, 5) is None       # a private chat has no message links
    assert message_link(-4242, 5) is None      # nor does a basic group
