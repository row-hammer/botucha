"""Run Botucha: `uv run python -m botucha --config config.toml`."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import Message, MessageReactionUpdated, ReactionTypeEmoji, ReplyParameters, User

from .app import Botucha, Incoming
from .config import load_config
from .images import MAX_SIDE
from .embed import OllamaEmbedder
from .llm import OllamaLLM
from .memory import Memory
from .prices import PriceClient
from .spell import Speller
from .store import Store
from .trace import Tracer

log = logging.getLogger("botucha")


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def pick_photo(sizes) -> object | None:
    """The largest size that fits MAX_SIDE, or the smallest one if none fits."""
    if not sizes:
        return None
    fits = [s for s in sizes if max(s.width, s.height) <= MAX_SIDE]
    if fits:
        return max(fits, key=lambda s: s.width * s.height)
    return min(sizes, key=lambda s: s.width * s.height)


def to_incoming(m: Message, me: User, *, edited: bool) -> Incoming:
    text = m.text or m.caption or ""
    user = m.from_user
    entities = m.entities or m.caption_entities or []
    mention = f"@{me.username}".lower() if me.username else None
    mentions_bot = bool(mention) and any(
        e.type == "mention" and text[e.offset:e.offset + e.length].lower() == mention for e in entities)
    parent = m.reply_to_message
    when = (m.edit_date if edited and m.edit_date else m.date)
    ts = when.timestamp() if hasattr(when, "timestamp") else float(when)
    return Incoming(
        chat_id=m.chat.id, msg_id=m.message_id, user_id=user.id if user else 0,
        name=user.full_name if user else "?", username=user.username if user else None,
        is_bot=bool(user and user.is_bot), ts=ts, text=text,
        reply_to=parent.message_id if parent else None,
        reply_to_bot=bool(parent and parent.from_user and parent.from_user.id == me.id),
        mentions_bot=mentions_bot, edited=edited,
        image_file_id=photo.file_id if (photo := pick_photo(m.photo)) else None)


class AiogramOutbox:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send(self, chat_id: int, texts: list[str], reply_to: int | None) -> list[int]:
        ids = []
        for t in texts:
            rp = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
            sent = await self.bot.send_message(chat_id, t, reply_parameters=rp)
            ids.append(sent.message_id)
        return ids

    async def react(self, chat_id: int, msg_id: int, emoji: str) -> None:
        await self.bot.set_message_reaction(chat_id, msg_id, reaction=[ReactionTypeEmoji(emoji=emoji)])

    async def leave(self, chat_id: int) -> None:
        await self.bot.leave_chat(chat_id)

    async def typing(self, chat_id: int) -> None:
        try:
            await self.bot.send_chat_action(chat_id, "typing")
        except Exception as e:
            log.debug("typing failed: %s", e)


async def main(config_path: Path) -> None:
    env = {**load_env(config_path.parent / ".env"), **os.environ}
    cfg = load_config(config_path, env)
    store = Store(cfg.paths.db)
    memory = Memory(store, OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model))
    tg = Bot(cfg.telegram.token)
    me = await tg.get_me()
    log.info("logged in as @%s (%d)", me.username, me.id)
    app = Botucha(cfg, store, memory, OllamaLLM(cfg.model), AiogramOutbox(tg), rng=random.Random(),
                  bot_user_id=me.id, bot_username=me.username or "", prices=PriceClient(), tracer=Tracer(store))
    app.speller = Speller(Path(__file__).resolve().parent.parent / "data" / "hunspell" / "lt", vocab=app.vocabulary)
    dp = Dispatcher()

    @dp.message()
    async def on_message(m: Message) -> None:
        await app.on_message(to_incoming(m, me, edited=False))

    @dp.message_reaction()
    async def on_reaction(r: MessageReactionUpdated) -> None:
        emojis = [x.emoji for x in r.new_reaction if isinstance(x, ReactionTypeEmoji)]
        await app.on_reaction(r.chat.id, r.message_id, r.user.id if r.user else None, emojis)

    @dp.edited_message()
    async def on_edit(m: Message) -> None:
        await app.on_message(to_incoming(m, me, edited=True))

    async def bootstrap() -> None:
        try:
            await app.bootstrap()
        except Exception:
            log.exception("bootstrap failed; it will retry on next start")

    tasks = [asyncio.create_task(app.worker.run()), asyncio.create_task(app.learn_loop()),
             asyncio.create_task(bootstrap()), asyncio.create_task(app.state_loop()),
             asyncio.create_task(app.maintenance_loop())]
    try:
        await dp.start_polling(tg, allowed_updates=["message", "edited_message", "message_reaction"])
    finally:
        await app.worker.stop()
        for t in tasks:
            t.cancel()
        await tg.session.close()


def cli() -> None:
    p = argparse.ArgumentParser(prog="botucha")
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main(args.config.resolve()))


if __name__ == "__main__":
    cli()
