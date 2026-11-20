"""Botucha core: ties storage, triggers, memory, generation and commands together.
Telegram specifics live in __main__.py behind the Outbox protocol and the Incoming shape."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from .brain import PromptContext, generate_reply
from .commands import CommandContext, handle_command, load_trigger_state, message_link, parse_command
from .config import Config
from .export_import import import_export, parse_export
from .learn import learn_once, profiles_due, refresh_profiles, should_learn
from .llm import LLM
from .memory import Memory
from .store import Store, StoredMessage
from .trigger import Decision, decide, fold, is_direct, is_recall, mark_unsolicited
from .worker import Job, ReplyWorker

log = logging.getLogger(__name__)

CANNED = "servas perkaito, palauk"
HISTORY_N = 40
BOT_NAME = "Botucha"
COMMAND_FAILED = "nepavyko, pabandyk veliau"
TG_LIMIT = 4000


@dataclass
class Incoming:
    chat_id: int
    msg_id: int
    user_id: int
    name: str
    username: str | None
    is_bot: bool
    ts: float
    text: str
    reply_to: int | None
    reply_to_bot: bool
    mentions_bot: bool
    edited: bool


@dataclass
class ReplyJob(Job):
    links: bool = False  # /atsimeni: append links to the original messages


class Outbox(Protocol):
    async def send(self, chat_id: int, texts: list[str], reply_to: int | None) -> list[int]: ...
    async def react(self, chat_id: int, msg_id: int, emoji: str) -> None: ...
    async def typing(self, chat_id: int) -> None: ...


def _read(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        log.warning("cannot read %s", path)
        return ""


class Botucha:
    def __init__(self, cfg: Config, store: Store, memory: Memory, llm: LLM, outbox: Outbox, *,
                 rng: random.Random, clock: Callable[[], float] = time.time, bot_user_id: int,
                 bot_username: str, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 started_at: float | None = None):
        self.cfg, self.store, self.memory, self.llm, self.outbox = cfg, store, memory, llm, outbox
        self.rng, self.clock, self.sleep = rng, clock, sleep
        self.bot_user_id, self.bot_username = bot_user_id, bot_username
        self.started_at = started_at if started_at is not None else clock()
        self.state = load_trigger_state(store, cfg.trigger)
        self.last_error: str | None = None
        self._ignored_chats: set[int] = set()
        self._bg_lock = asyncio.Lock()  # bootstrap and learning never overlap
        self.worker = ReplyWorker(self.run_job, quiet_s=cfg.trigger.burst_quiet_s,
                                  max_wait_s=cfg.trigger.burst_max_s)

    # ---- incoming --------------------------------------------------------
    async def on_message(self, m: Incoming) -> None:
        if m.chat_id not in self.cfg.telegram.chat_ids:
            if m.chat_id not in self._ignored_chats:
                self._ignored_chats.add(m.chat_id)
                log.info("ignoring chat %d (add it to telegram.chat_ids in config.toml to enable)", m.chat_id)
            return
        if m.edited:
            self.store.update_message_text(m.chat_id, m.msg_id, m.text)
            return
        own = m.is_bot or m.user_id == self.bot_user_id
        self.store.add_message(StoredMessage(m.chat_id, m.msg_id, m.user_id, m.name, m.ts, m.text,
                                             m.reply_to, own))
        if not own:
            self.store.upsert_member(m.user_id, m.name, m.username)
        self.worker.activity()
        now = self.clock()

        if m.text.startswith("/") and not own:
            parsed = parse_command(m.text, self.bot_username)
            if parsed and m.ts < self.started_at:
                return  # sent while offline: stored, never executed or answered (spec §4)
            if parsed:
                name, args = parsed
                if name in ("rimtai", "atsimeni") and m.ts >= self.started_at and self.state.enabled:
                    self.worker.submit(ReplyJob(m.chat_id, m.msg_id, direct=True, serious=name == "rimtai",
                                                recall=name == "atsimeni", links=name == "atsimeni"))
                    return
                ctx = CommandContext(self.memory, self.store, self.state, self.cfg, self.started_at,
                                     self.last_error, m.chat_id)
                try:
                    reply = await handle_command(name, args, m.user_id, now, ctx)
                except Exception as e:
                    log.exception("command /%s failed", name)
                    self.last_error = f"/{name}: {type(e).__name__}: {e}"
                    reply = COMMAND_FAILED
                if reply:
                    if len(reply) > TG_LIMIT:
                        reply = reply[:TG_LIMIT - 1] + "…"
                    try:
                        await self.outbox.send(m.chat_id, [reply], m.msg_id)
                    except Exception as e:
                        log.warning("command reply failed: %s", e)
                        self.last_error = f"send: {e}"
                return

        direct = is_direct(m.text, reply_to_bot=m.reply_to_bot, mentions_bot=m.mentions_bot,
                           name_regex=self.cfg.telegram.bot_name_regex)
        decision = decide(m.text, sender_is_bot=own, direct=direct, started_at=self.started_at, msg_ts=m.ts,
                          now=now, state=self.state, cfg=self.cfg.trigger, rng=self.rng)
        if decision is Decision.REPLY:
            if not direct:
                mark_unsolicited(self.state, now)
            self.worker.submit(ReplyJob(m.chat_id, m.msg_id, direct=direct,
                                        serious=direct and "rimtai" in fold(m.text), recall=is_recall(m.text)))
        elif decision is Decision.REACT:
            mark_unsolicited(self.state, now)
            try:
                await self.outbox.react(m.chat_id, m.msg_id, self.rng.choice(self.cfg.trigger.reactions))
            except Exception as e:
                log.warning("reaction failed: %s", e)

    # ---- replies ---------------------------------------------------------
    def _member_names(self) -> list[str]:
        names = []
        for mem in self.store.members().values():
            names.append(mem.name)
            if mem.username:
                names.append(mem.username)
        return names

    async def run_job(self, jobs: list[Job]) -> None:
        by_chat: dict[int, list[Job]] = {}
        for j in jobs:
            by_chat.setdefault(j.chat_id, []).append(j)
        for chat_id, chat_jobs in by_chat.items():
            await self._reply(chat_id, chat_jobs)

    async def _reply(self, chat_id: int, jobs: list[Job]) -> None:
        direct = [j for j in jobs if j.direct]
        recall = any(j.recall for j in jobs)
        links = any(getattr(j, "links", False) for j in jobs)
        try:
            await self.memory.index_new_chunks(chat_id)
            history = self.store.recent_messages(chat_id, HISTORY_N)
            ids = {j.msg_id for j in jobs}
            query = "\n".join(m.text for m in history if m.msg_id in ids) or (history[-1].text if history else "")
            hits = await self.memory.search_chunks(query, k=6 if recall else 3, chat_id=chat_id)
            facts = await self.memory.search_facts(query, k=5)
            members = self.store.members()
            ctx = PromptContext(
                persona=_read(self.cfg.paths.persona), style_examples=_read(self.cfg.paths.style_examples),
                profiles={members[u].name: p for u, p in self.memory.profiles().items() if u in members},
                slang=[f.text for f in self.memory.slang_in([m.text for m in history])],
                chunks=[h.chunk.text for h in hits], facts=[f.text for f in facts], history=history,
                bot_user_id=self.bot_user_id, serious=any(j.serious for j in jobs))
            await self.outbox.typing(chat_id)
            texts = await generate_reply(self.llm, ctx, num_predict=self.cfg.model.num_predict,
                                         max_chars=self.cfg.model.num_ctx * 3, member_names=self._member_names())
        except Exception as e:
            log.exception("reply preparation failed")
            self.last_error = f"{type(e).__name__}: {e}"
            texts = None
        if texts is None:
            self.last_error = self.last_error or "model returned nothing"
            if direct:
                await self._send(chat_id, [CANNED], direct[-1].msg_id, store=False)
            return
        if links and hits:
            texts = texts + [" ".join(message_link(h.chunk.chat_id, h.chunk.first_msg_id) for h in hits[:3])]
        await self._send(chat_id, texts, direct[-1].msg_id if direct else None, store=True)

    async def _send(self, chat_id: int, texts: list[str], reply_to: int | None, *, store: bool) -> None:
        for i, text in enumerate(texts):
            if i:
                await self.outbox.typing(chat_id)
                await self.sleep(self.rng.uniform(1.0, 2.0))
            try:
                sent = await self.outbox.send(chat_id, [text], reply_to if i == 0 else None)
            except Exception as e:
                log.warning("send failed: %s", e)
                self.last_error = f"send: {e}"
                return
            if store and not text.startswith("https://t.me/"):
                for mid in sent:
                    self.store.add_message(StoredMessage(chat_id, mid, self.bot_user_id, BOT_NAME, self.clock(),
                                                         text, None, True))

    # ---- background ------------------------------------------------------
    async def learn_tick(self) -> None:
        async with self._bg_lock:
            try:
                await self._learn_tick()
            except Exception as e:
                log.exception("learning failed")
                self.last_error = f"learn: {e}"

    async def _learn_tick(self) -> None:
        for chat_id in self.cfg.telegram.chat_ids:
            last = self.store.recent_messages(chat_id, 1)
            if not last:
                continue
            key = f"learned_rowid:{chat_id}"
            new = self.store.last_rowid(chat_id) - int(self.store.get_state(key, "0"))
            if not should_learn(now=self.clock(), last_msg_ts=last[0].ts, new_msgs=new,
                                reply_pending=self.worker.pending):
                continue
            await self.memory.index_new_chunks(chat_id, force=True)
            await learn_once(self.memory, self.llm, chat_id)
            self.store.set_state(key, str(self.store.last_rowid(chat_id)))
            if profiles_due(self.store, chat_id):
                await refresh_profiles(self.memory, self.llm, self.store, chat_id)

    async def learn_loop(self, every_s: float = 60.0) -> None:
        while True:
            await asyncio.sleep(every_s)
            await self.learn_tick()

    async def bootstrap(self) -> None:
        async with self._bg_lock:
            await self._bootstrap()

    async def _bootstrap(self) -> None:
        export = self.cfg.paths.export
        if not export or self.store.get_state("export_imported") == "1":
            return
        if not export.exists():
            log.warning("export %s not found, skipping bootstrap", export)
            return
        chat_id, _ = parse_export(export)
        n = import_export(self.store, export)
        log.info("imported %d messages from export", n)
        await self.memory.index_new_chunks(chat_id, force=True)
        await learn_once(self.memory, self.llm, chat_id)
        await refresh_profiles(self.memory, self.llm, self.store, chat_id)
        self.store.set_state(f"learned_rowid:{chat_id}", str(self.store.last_rowid(chat_id)))
        self.store.set_state("export_imported", "1")
