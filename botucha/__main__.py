"""Run Botucha: `uv run python -m botucha --config config.toml`."""
from __future__ import annotations

import argparse
import io
import asyncio
import logging
import os
import random
from collections.abc import Callable
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import Message, MessageReactionUpdated, ReactionTypeEmoji, ReplyParameters, User

from .app import Botucha, Incoming
from .config import load_config
from .images import MAX_IMAGE_BYTES, MAX_SIDE
from .embed import OllamaEmbedder
from .llm import OllamaLLM
from .memory import Memory
from .prices import PriceClient
from .proofread import ClaudeProofreader
from .reactions import DEFAULT_EXAMPLES, NO_REACTION, ReactionPicker
from .spell import Speller
from .store import Store
from .trace import Tracer

log = logging.getLogger("botucha")

DRAIN_S = 60  # on stop, a reply being generated gets this long to go out (systemd waits TimeoutStopSec)


def watch(task: asyncio.Task, on_fail: Callable[[], None]) -> None:
    """A background loop that dies with an error stops the bot, so systemd restarts it instead of the bot
    running on without learning, backups or the reply worker."""
    def done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            log.critical("background task %s died", t.get_coro().__qualname__, exc_info=t.exception())
            on_fail()
    task.add_done_callback(done)


async def shutdown(app: Botucha, tasks: list[asyncio.Task], *, drain_s: float = DRAIN_S) -> None:
    """Let the reply being generated (and any queued behind it) go out, keep what did not make it for the
    next start, then stop the loops."""
    left = await app.worker.drain(drain_s)
    app._persist_pending()  # the unanswered part of the running batch and the queue, never what already went out
    if left:
        log.warning("stopping with %d reply(s) unfinished; they are answered after the restart", len(left))
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


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
        # a GIF is seen through its preview frame (Telegram makes one for every animation)
        image_file_id=image.file_id if (image := pick_photo(m.photo) or (
            m.animation.thumbnail if m.animation else None)) else None,
        gif=m.animation is not None)


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

    async def fetch_image(self, file_id: str) -> bytes:
        """Download a photo into memory (never to disk)."""
        f = await self.bot.get_file(file_id)
        if f.file_size and f.file_size > MAX_IMAGE_BYTES:
            raise ValueError(f"image too large ({f.file_size} bytes)")
        buf = io.BytesIO()
        await self.bot.download_file(f.file_path, destination=buf)
        return buf.getvalue()

    async def typing(self, chat_id: int) -> None:
        try:
            await self.bot.send_chat_action(chat_id, "typing")
        except Exception as e:
            log.debug("typing failed: %s", e)


async def main(config_path: Path) -> None:
    env = {**load_env(config_path.parent / ".env"), **os.environ}
    cfg = load_config(config_path, env)
    store = Store(cfg.paths.db)
    memory = Memory(store, OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model, keep_alive=cfg.model.keep_alive))
    tg = Bot(cfg.telegram.token)
    me = await tg.get_me()
    log.info("logged in as @%s (%d)", me.username, me.id)
    llm = OllamaLLM(cfg.model)
    found = await llm.has_vision()
    vision = bool(found)
    log.info("model %s, vision: %s", cfg.model.chat_model,
             {True: "yes", False: "no (photos are kept as text only)", None: "unknown, Ollama not answering yet (retrying)"}[found])
    app = Botucha(cfg, store, memory, llm, AiogramOutbox(tg), rng=random.Random(), vision=vision,
                  bot_user_id=me.id, bot_username=me.username or "", prices=PriceClient(), tracer=Tracer(store))
    app.vision_check = llm.has_vision
    examples = {**DEFAULT_EXAMPLES, **{(NO_REACTION if k.lower() == "none" else k): list(v)
                                       for k, v in cfg.reaction_examples}}
    app.reaction_picker = ReactionPicker(memory.embedder, cfg.trigger.reactions, examples)
    app.speller = Speller(Path(__file__).resolve().parent.parent / "data" / "hunspell" / "lt", vocab=app.vocabulary)
    if cfg.claude.enabled:
        app.proofreader = ClaudeProofreader(cfg.claude, store, api_key=env.get("ANTHROPIC_API_KEY", "").strip() or None)
        st = app.proofreader.status()
        log.info("claude proofreading: %s (%s, until %s, %d/%d calls today)",
                 "on" if st["allowed"] else f"off, {st['reason']}", cfg.claude.model, st["until"] or "no end date",
                 st["calls_today"], st["daily_limit"])
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

    app.warm_prompt_cache = True

    async def bootstrap() -> None:
        try:
            await app.bootstrap()
        except Exception:
            log.exception("bootstrap failed; it will retry on next start")
        await app.warm_prompt()  # after the import: its learning run would push the block out again

    tasks = [asyncio.create_task(app.worker.run()), asyncio.create_task(app.learn_loop()),
             asyncio.create_task(bootstrap()), asyncio.create_task(app.state_loop()),
             asyncio.create_task(app.maintenance_loop())]
    failed = []

    def fail() -> None:
        failed.append(True)
        asyncio.get_running_loop().create_task(dp.stop_polling())
    for t in tasks:
        watch(t, fail)
    app.recover()  # replies the last run did not get to, and traces it left open
    try:
        await dp.start_polling(tg, allowed_updates=["message", "edited_message", "message_reaction"])
    finally:
        await shutdown(app, tasks)
        await tg.session.close()
    if failed:
        raise SystemExit(1)  # Restart=on-failure needs a non-zero exit


def cli() -> None:
    p = argparse.ArgumentParser(prog="botucha")
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main(args.config.resolve()))


if __name__ == "__main__":
    cli()
