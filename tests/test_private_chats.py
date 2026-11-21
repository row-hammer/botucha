"""A private chat with the bot is not the group's memory: nothing written there is learned."""
import dataclasses

from botucha.store import StoredMessage
from tests.test_app import C, app, inc  # noqa: F401  (app is a fixture)

P = 4242  # a configured private chat: Telegram gives users positive ids


def with_private_chat(bot):
    bot.cfg = dataclasses.replace(bot.cfg, telegram=dataclasses.replace(bot.cfg.telegram, chat_ids=(C, P)))


def fill(store, chat_id, text, n=40):
    for i in range(n):
        store.add_message(StoredMessage(chat_id, i + 1, 111, "Tadas", 100.0 + i, text))


async def test_private_chat_is_never_learned_from(app):
    bot, store, llm, _ = await app(['{"facts": [{"about": null, "text": "Tadas slepia nuostolius"}], "slang": []}']
                                   + ["profilis"] * 5)
    with_private_chat(bot)
    store.upsert_member(111, "Tadas", "tadas")
    fill(store, P, "slaptas dalykas apie nuostolius")
    bot.clock = lambda: 1e12  # everything looks idle and old

    await bot.learn_tick()

    assert llm.calls == []  # no extraction and no profile refresh from private lines
    assert store.conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0
    assert bot.memory.profiles() == {}


async def test_group_is_still_learned_next_to_a_private_chat(app):
    bot, store, llm, _ = await app(['{"facts": [{"about": null, "text": "Tadas perka nvidia"}], "slang": []}']
                                   + ["profilis"] * 5)
    with_private_chat(bot)
    store.upsert_member(111, "Tadas", "tadas")
    fill(store, C, "perku nvidia akcijas")
    fill(store, P, "slaptas dalykas apie nuostolius")
    bot.clock = lambda: 1e12

    await bot.learn_tick()

    extractions = [c for c in llm.calls if c["fmt_json"]]
    assert len(extractions) == 1
    sent = " ".join(m["content"] for c in llm.calls for m in c["messages"])
    assert "nvidia" in sent and "slaptas" not in sent
    assert [r[0] for r in store.conn.execute("SELECT text FROM facts")] == ["Tadas perka nvidia"]


async def test_private_chat_words_are_not_group_vocabulary(app):
    bot, store, _, _ = await app()
    with_private_chat(bot)
    store.add_message(StoredMessage(C, 1, 111, "Tadas", 100.0, "grupinis zodis"))
    store.add_message(StoredMessage(P, 1, 111, "Tadas", 101.0, "privatuszodis"))

    words = bot.vocabulary()

    assert "grupinis" in words and "privatuszodis" not in words


async def test_teaching_him_in_a_private_chat_still_works(app):
    bot, store, _, out = await app()
    with_private_chat(bot)

    await bot.on_message(inc("/isimink Tadas turi daug coreweave", chat=P))

    assert [r[0] for r in store.conn.execute("SELECT text FROM facts")] == ["Tadas turi daug coreweave"]
    assert out.sent[-1][1].startswith("isiminiau")


async def test_an_imported_private_chat_is_stored_but_not_learned_from(app, tmp_path):
    """Review finding: the first-start import learned from any export, so a private chat's export went into
    the group's facts and profiles."""
    import json
    export = tmp_path / "result.json"
    export.write_text(json.dumps({"id": P, "type": "personal_chat", "messages": [
        {"id": i + 1, "type": "message", "from": "Tadas", "from_id": "user111", "date_unixtime": str(100 + i * 4000),
         "text": f"slaptas dalykas {i}"} for i in range(40)]}), encoding="utf-8")
    bot, store, llm, _ = await app(['{"facts": [{"about": null, "text": "Tadas slepia"}], "slang": []}'] + ["p"] * 5,
                                   export=export)
    with_private_chat(bot)
    await bot.bootstrap()
    chat = store.conn.execute("SELECT DISTINCT chat_id FROM messages").fetchall()
    assert chat and chat[0][0] > 0 and store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 40
    assert llm.calls == [] and bot.memory.all_facts() == [] and bot.memory.profiles() == {}
    assert store.get_state("export_imported") == "1"
