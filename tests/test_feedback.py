from botucha.feedback import score_for_reactions
from botucha.store import Store, StoredMessage
from tests.test_app import BOT_ID, C, app, inc, settle  # noqa: F401  (app is a fixture)


def test_reaction_mapping():
    assert score_for_reactions(["👍"]) == 1
    assert score_for_reactions(["🤣", "🔥"]) == 1
    assert score_for_reactions(["👎"]) == -1
    assert score_for_reactions(["👍", "💩"]) == -1  # any bad wins
    assert score_for_reactions(["🤡"]) is None
    assert score_for_reactions([]) is None


def test_store_one_vote_per_person():
    s = Store(":memory:")
    s.add_message(StoredMessage(C, 50, BOT_ID, "Botucha", 1.0, "hodlinam", is_bot=True))
    s.set_feedback(C, 50, 111, 1, None, 2.0)
    s.set_feedback(C, 50, 111, -1, "per daug akciju", 3.0)
    s.set_feedback(C, 50, 222, 1, None, 4.0)
    assert s.feedback_totals() == (1, 1)
    bad = s.recent_bad_feedback(10)
    assert [(b.text, b.reason) for b in bad] == [("hodlinam", "per daug akciju")]
    s.clear_feedback(C, 50, 222)
    assert s.feedback_totals() == (0, 1)


async def _bot_message(bot, store, msg_id=50, text="hodlinam iki nulio"):
    store.add_message(StoredMessage(C, msg_id, BOT_ID, "Botucha", 9_500.0, text, is_bot=True))


async def test_reaction_on_bot_message_counts(app):
    bot, store, _, _ = await app()
    await _bot_message(bot, store)
    await bot.on_reaction(C, 50, 111, ["🔥"])
    assert store.feedback_totals() == (1, 0)
    await bot.on_reaction(C, 50, 111, [])  # reaction removed
    assert store.feedback_totals() == (0, 0)


async def test_reaction_on_member_message_ignored(app):
    bot, store, _, _ = await app()
    await bot.on_message(inc("nu jo", msg_id=60))
    await bot.on_reaction(C, 60, 222, ["👍"])
    assert store.feedback_totals() == (0, 0)


async def test_reaction_foreign_chat_ignored(app):
    bot, store, _, _ = await app()
    await bot.on_reaction(-5, 50, 111, ["👍"])
    assert store.feedback_totals() == (0, 0)


async def test_blogai_with_reason(app):
    bot, store, llm, out = await app()
    await _bot_message(bot, store)
    await bot.on_message(inc("/blogai per daug apie akcijas", msg_id=61, reply_to=50, reply_to_bot=True))
    assert store.feedback_totals() == (0, 1)
    assert store.recent_bad_feedback(1)[0].reason == "per daug apie akcijas"
    assert "užrašiau" in out.sent[-1][1] and llm.calls == []


async def test_gerai(app):
    bot, store, _, out = await app()
    await _bot_message(bot, store)
    await bot.on_message(inc("/gerai", msg_id=62, reply_to=50, reply_to_bot=True))
    assert store.feedback_totals() == (1, 0)


async def test_blogai_without_reply_asks_for_reply(app):
    bot, store, _, out = await app()
    await bot.on_message(inc("/blogai", msg_id=63))
    assert store.feedback_totals() == (0, 0)
    assert "reply" in out.sent[-1][1]


async def test_ivertinimai_admin_only(app):
    bot, store, _, out = await app()
    await _bot_message(bot, store)
    store.set_feedback(C, 50, 111, -1, "nejuokinga", 1.0)
    await bot.on_message(inc("/ivertinimai", msg_id=64))
    assert out.sent[-1][1] == "tik bosas gali"
    admin = bot.cfg.telegram.admin_id
    await bot.on_message(inc("/ivertinimai", msg_id=65, user=admin))
    reply = out.sent[-1][1]
    assert "👍 0" in reply and "👎 1" in reply and "hodlinam iki nulio" in reply and "nejuokinga" in reply
