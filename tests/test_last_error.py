"""last_error says what is wrong now: it clears when that kind of work succeeds again, and on a new start."""
import asyncio
import dataclasses

from botucha.app import Botucha
from tests.test_app import C, app, inc  # noqa: F401  (app is a fixture)


async def test_a_new_start_begins_without_the_old_error(app):
    bot, store, llm, out = await app()
    bot.last_error = "send: boom"
    Botucha(bot.cfg, store, bot.memory, llm, out, rng=bot.rng, clock=bot.clock, bot_user_id=bot.bot_user_id,
            bot_username="b", sleep=bot.sleep)
    assert store.get_state("last_error") == ""


async def test_a_good_reply_clears_a_reply_error_but_not_a_backup_error(app):
    bot, store, _, _ = await app(["labas", "labas"])
    bot.last_error = "send: Telegram timed out"
    await bot.on_message(inc("botucha labas", msg_id=1))
    await asyncio.sleep(0.15)
    assert not bot.last_error and store.get_state("last_error") == ""
    bot.last_error = "backup: OSError: disk full"
    await bot.on_message(inc("botucha labas", msg_id=2))
    await asyncio.sleep(0.15)
    assert bot.last_error == "backup: OSError: disk full"


async def test_a_good_backup_clears_a_backup_error(app, tmp_path):
    bot, store, _, _ = await app()
    bot.cfg = dataclasses.replace(bot.cfg, paths=dataclasses.replace(bot.cfg.paths, db=tmp_path / "botucha.db"))
    bot.clock = lambda: 1_795_300_000.0
    bot.last_error = "backup: OSError: disk full"
    bot.maintenance_tick()
    assert not bot.last_error


async def test_a_good_learning_run_clears_a_learning_error(app):
    bot, _, _, _ = await app()
    bot.last_error = "learn: ConnectionError: ollama down"
    await bot.learn_tick()
    assert not bot.last_error


async def test_an_error_from_this_batch_is_not_cleared_by_another_chat_in_it(app):
    bot, _, _, _ = await app()
    bot._batch_seq = bot._error_seq
    bot.last_error = "OperationalError: database is locked"  # chat A, same batch
    bot._clear_error("reply", since=bot._batch_seq)           # chat B succeeded
    assert bot.last_error == "OperationalError: database is locked"
