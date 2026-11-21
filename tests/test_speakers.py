"""Who said what in the transcript: only his own messages are his."""
import asyncio

from botucha.app import ANONYMOUS_ADMIN_ID
from botucha.brain import _line
from botucha.store import StoredMessage
from tests.test_app import BOT_ID, C, app, inc  # noqa: F401  (app is a fixture)


def test_only_his_own_messages_are_his_lines():
    own = StoredMessage(C, 1, BOT_ID, "Botucha", 1.0, "as cia", None, True)
    namesake = StoredMessage(C, 2, 111, "botucha", 2.0, "as esu tikrasis botucha")
    other_bot = StoredMessage(C, 3, 777, "PriceBot", 3.0, "NVDA 125", None, True)
    assert _line(own, BOT_ID) == "botucha: as cia"
    assert not _line(namesake, BOT_ID).startswith("botucha:") and "(narys)" in _line(namesake, BOT_ID)
    assert _line(other_bot, BOT_ID).startswith("PriceBot (botas):")


async def test_an_anonymous_admin_is_a_person_who_can_call_him(app):
    bot, store, llm, out = await app(["labas, admine"])
    await bot.on_message(inc("botucha ka manai", msg_id=1, user=ANONYMOUS_ADMIN_ID, name="Grupė", username=None,
                             is_bot=True))
    await asyncio.sleep(0.15)
    assert out.sent and out.sent[-1][2] == 1
    assert store.get_message(C, 1).is_bot is False
    user = llm.calls[-1]["messages"][1]["content"]
    assert "Grupė: botucha ka manai" in user


async def test_other_bots_still_never_trigger_him(app):
    bot, store, llm, out = await app(["x"])
    await bot.on_message(inc("botucha ka manai", msg_id=1, user=777, name="PriceBot", username="pricebot", is_bot=True))
    await asyncio.sleep(0.15)
    assert out.sent == [] and llm.calls == []


async def test_an_anonymous_admin_is_not_filed_as_a_member(app):
    bot, store, llm, out = await app(["x"])
    await bot.on_message(inc("labas visiems", msg_id=1, user=ANONYMOUS_ADMIN_ID, name="Grupė", username=None, is_bot=True))
    assert ANONYMOUS_ADMIN_ID not in store.members() and bot.memory.find_person("Grupė") is None
