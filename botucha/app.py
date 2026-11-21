"""Botucha core: ties storage, triggers, memory, generation and commands together.
Telegram specifics live in __main__.py behind the Outbox protocol and the Incoming shape."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from collections import defaultdict, deque
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .backup import daily_backup
from .images import (DESCRIBE_NUM_PREDICT, DESCRIBE_PROMPT, DESCRIBE_TIMEOUT_S, FETCH_TIMEOUT_S, IMAGE_GUARD,
                     IMAGE_WINDOW_S, MAX_IMAGE_BYTES, caption_of, clean_description, described_text,
                     description_of, image_text, retag)
from .llm import chat_ex
from .brain import PromptContext, generate_reply_ex
from .commands import CommandContext, handle_command, load_trigger_state, message_link, parse_command
from .config import Config
from .export_import import import_export, parse_export
from .feedback import score_for_reactions
from .proofread import known_words, spelling_notes
from .prices import DEFAULT_ALIASES, PriceClient, detect_symbols, format_quote
from .learn import LEARN_MAX_CALLS, learn_once, profiles_due, refresh_profiles, should_learn, unlearned
from .llm import LLM
from .memory import EMBED_BATCH, Memory
from .store import Store, StoredMessage
from .trace import NULL_RUN, Tracer, prune_traces
from .trigger import Decision, decide_with_reason, fold, is_direct, is_recall, mark_unsolicited
from .worker import Job, ReplyWorker

log = logging.getLogger(__name__)

CANNED = "servas perkaito, palauk"
HISTORY_N = 40
OWN_LINES_IN_HISTORY = 5  # fewer of his own lines = less copying himself
RECENT_OWN_N = 20
VISION_RECHECK_S = 300
BOT_NAME = "Botucha"
COMMAND_FAILED = "nepavyko, pabandyk veliau"
TG_LIMIT = 4000
FEEDBACK_ALIASES = {"geras": "gerai", "blogas": "blogai"}


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
    image_file_id: str | None = None  # a photo: only Telegram's id, downloaded when he replies


@dataclass
class ReplyJob(Job):
    links: bool = False  # /atsimeni: append links to the original messages


class Outbox(Protocol):
    async def send(self, chat_id: int, texts: list[str], reply_to: int | None) -> list[int]: ...
    async def react(self, chat_id: int, msg_id: int, emoji: str) -> None: ...
    async def typing(self, chat_id: int) -> None: ...
    async def leave(self, chat_id: int) -> None: ...
    async def fetch_image(self, file_id: str) -> bytes: ...


def is_private(chat_id: int) -> bool:
    """Telegram gives users positive ids and groups negative ones."""
    return chat_id > 0


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
                 started_at: float | None = None, prices: PriceClient | None = None,
                 tracer: Tracer | None = None, vision: bool = False):
        self.cfg, self.store, self.memory, self.llm, self.outbox = cfg, store, memory, llm, outbox
        self.rng, self.clock, self.sleep = rng, clock, sleep
        self.bot_user_id, self.bot_username = bot_user_id, bot_username
        self.started_at = started_at if started_at is not None else clock()
        self.state = load_trigger_state(store, cfg.trigger)
        self.state.quiet_until = float(store.get_state("quiet_until", "0") or 0)
        self.tracer = tracer
        self.vision = vision  # the chat model can see images (checked at startup)
        self.vision_check: Callable[[], Awaitable[bool | None]] | None = None  # set by __main__
        self._vision_checked_at = -1e18
        self._last_error: str | None = None
        store.set_state("bot_started_at", str(self.started_at))
        self._ignored_chats: set[int] = set()
        self._locked = frozenset(cfg.memory.locked_members)
        self.prices = prices if cfg.prices.enabled else None
        self.speller = None  # set by __main__: Speller(dict, vocab=self.vocabulary)
        self.proofreader = None  # set by __main__ when [claude] is configured: ClaudeProofreader
        self.aliases = {**DEFAULT_ALIASES, **dict(cfg.prices.aliases)}
        self._calls: dict[int, deque[float]] = defaultdict(deque)
        self._bg_lock = asyncio.Lock()  # bootstrap and learning never overlap
        self.worker = ReplyWorker(self.run_job, quiet_s=cfg.trigger.burst_quiet_s,
                                  max_wait_s=cfg.trigger.burst_max_s)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @last_error.setter
    def last_error(self, value: str | None) -> None:
        self._last_error = value
        try:
            self.store.set_state("last_error", value or "")
        except Exception as e:
            log.warning("cannot store last error: %s", e)

    def sync_state(self) -> None:
        """Pick up on/off, frequency and quiet time written by the web dashboard."""
        g = self.store.get_state
        self.state.enabled = g("enabled", "1") == "1"
        self.state.random_n = int(g("random_n", str(self.state.random_n)) or self.state.random_n)
        self.state.quiet_until = float(g("quiet_until", "0") or 0)

    async def state_loop(self, every_s: float = 5.0) -> None:
        while True:
            await asyncio.sleep(every_s)
            try:
                self.sync_state()
            except Exception as e:
                log.warning("state sync failed: %s", e)

    def maintenance_tick(self) -> None:
        """Hourly: drop old traces, and make today's database backup if there is none yet."""
        try:
            prune_traces(self.store, self.clock())
        except Exception as e:
            log.warning("trace cleanup failed: %s", e)
        try:
            folder = Path(self.cfg.paths.db).parent / "backups" / "daily"
            made = daily_backup(self.store.conn, folder, dt.date.fromtimestamp(self.clock()))
            if made:
                log.info("database backup written: %s", made.name)
        except Exception as e:
            log.warning("database backup failed: %s", e)
            self.last_error = f"backup: {type(e).__name__}: {e}"

    async def maintenance_loop(self, every_s: float = 3600.0) -> None:
        while True:
            self.maintenance_tick()  # same connection as the bot; a few MB copy in well under a second
            await asyncio.sleep(every_s)

    # ---- incoming --------------------------------------------------------
    async def on_message(self, m: Incoming) -> None:
        if m.chat_id not in self.cfg.telegram.chat_ids:
            if m.chat_id not in self._ignored_chats:
                self._ignored_chats.add(m.chat_id)
                log.info("ignoring chat %d (add it to telegram.chat_ids in config.toml to enable)", m.chat_id)
                if m.chat_id < 0:  # a group nobody configured: leave it
                    try:
                        await self.outbox.leave(m.chat_id)
                        log.info("left unknown chat %d", m.chat_id)
                    except Exception as e:
                        log.warning("could not leave chat %d: %s", m.chat_id, e)
            return
        command_text = m.text  # a photo's caption can be a command (/rimtai on a chart)
        if m.image_file_id:
            if m.edited:  # caption fixed later: keep a description already written
                old = self.store.get_message(m.chat_id, m.msg_id)
                m.text = retag(old.text if old else None, m.text)
            else:
                m.text = image_text(m.text)
        if m.edited:
            self.store.update_message_text(m.chat_id, m.msg_id, m.text)
            return
        own = m.is_bot or m.user_id == self.bot_user_id
        self.store.add_message(StoredMessage(m.chat_id, m.msg_id, m.user_id, m.name, m.ts, m.text,
                                             m.reply_to, own, m.image_file_id))
        if not own:
            self.store.upsert_member(m.user_id, m.name, m.username)
            self.memory.ensure_member_person(m.user_id, m.name, m.username)
        self.worker.activity()
        now = self.clock()

        if command_text.startswith("/") and not own:
            parsed = parse_command(command_text, self.bot_username)
            if parsed and m.ts < self.started_at:
                return  # sent while offline: stored, never executed or answered (spec §4)
            if parsed:
                name, args = parsed
                if name in ("rimtai", "atsimeni") and m.ts >= self.started_at and self.state.enabled:
                    self.worker.submit(ReplyJob(m.chat_id, m.msg_id, direct=True, serious=name == "rimtai",
                                                recall=name == "atsimeni", links=name == "atsimeni",
                                                trigger="serious" if name == "rimtai" else "recall"))
                    return
                if name == "kaina":
                    await self._command_price(m, args)
                    return
                name = FEEDBACK_ALIASES.get(name, name)
                if name in ("gerai", "blogai", "pataisyk"):
                    await self._command_feedback(m, name, args)
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

        direct = is_private(m.chat_id) or is_direct(  # a private chat is always talking to him
            m.text, reply_to_bot=m.reply_to_bot, mentions_bot=m.mentions_bot,
            name_regex=self.cfg.telegram.bot_name_regex)
        decision, reason = decide_with_reason(m.text, sender_is_bot=own, direct=direct, started_at=self.started_at,
                                              msg_ts=m.ts, now=now, state=self.state, cfg=self.cfg.trigger,
                                              rng=self.rng)
        if decision is Decision.REPLY and direct and self._over_limit(m.user_id, now):
            calls = self._calls[m.user_id]
            if len(calls) == self.cfg.trigger.user_calls_per_min + 1:  # react once per flood
                try:
                    await self.outbox.react(m.chat_id, m.msg_id, "🥱")
                except Exception as e:
                    log.warning("reaction failed: %s", e)
            return
        if decision is Decision.REPLY:
            if not direct:
                mark_unsolicited(self.state, now)
            self.worker.submit(ReplyJob(m.chat_id, m.msg_id, direct=direct,
                                        serious=direct and "rimtai" in fold(m.text), recall=is_recall(m.text),
                                        trigger=reason))
        elif decision is Decision.REACT:
            mark_unsolicited(self.state, now)
            try:
                await self.outbox.react(m.chat_id, m.msg_id, self.rng.choice(self.cfg.trigger.reactions))
            except Exception as e:
                log.warning("reaction failed: %s", e)

    def _is_own(self, chat_id: int, msg_id: int | None) -> bool:
        if msg_id is None:
            return False
        msg = self.store.get_message(chat_id, msg_id)
        return bool(msg and msg.user_id == self.bot_user_id)

    async def _command_feedback(self, m: Incoming, name: str, args: str) -> None:
        if not self._is_own(m.chat_id, m.reply_to):
            reply = "atsakyk (reply) į mano žinutę su /gerai, /blogai arba /pataisyk"
        elif name == "pataisyk":
            if not args:
                reply = "naudok: /pataisyk <kaip turėjau atsakyti>"
            else:
                self.store.set_correction(m.chat_id, m.reply_to, m.user_id, args, self.clock())
                reply = "ačiū, užrašiau pataisymą"
        else:
            self.store.set_feedback(m.chat_id, m.reply_to, m.user_id, 1 if name == "gerai" else -1,
                                    args or None, self.clock())
            reply = "ačiū, užrašiau"
        await self.outbox.send(m.chat_id, [reply], m.msg_id)

    async def _command_price(self, m: Incoming, args: str) -> None:
        if not args:
            reply = "naudok: /kaina <tickeris arba pavadinimas>, pvz. /kaina nvda"
        elif self.prices is None:
            reply = "kainos išjungtos"
        else:
            symbols = detect_symbols(args, self.aliases) or [args.split()[0].lstrip("$").upper()]
            quotes = await self.prices.quotes(symbols)
            reply = "\n".join(format_quote(q) for q in quotes) if quotes else f"nerandu tokio tickerio: {args}"
        await self.outbox.send(m.chat_id, [reply], m.msg_id)

    async def on_reaction(self, chat_id: int, msg_id: int, user_id: int | None, emojis: list[str]) -> None:
        """A member changed their reaction on a message. Only reactions on Botucha's messages count."""
        if chat_id not in self.cfg.telegram.chat_ids or user_id is None or not self._is_own(chat_id, msg_id):
            return
        score = score_for_reactions(emojis)
        if score is None:
            self.store.clear_feedback(chat_id, msg_id, user_id)
        else:
            self.store.set_feedback(chat_id, msg_id, user_id, score, None, self.clock())

    def _over_limit(self, user_id: int, now: float) -> bool:
        calls = self._calls[user_id]
        while calls and now - calls[0] > 60:
            calls.popleft()
        calls.append(now)
        return len(calls) > self.cfg.trigger.user_calls_per_min

    # ---- replies ---------------------------------------------------------
    def _trim_own(self, history: list[StoredMessage]) -> list[StoredMessage]:
        own = [i for i, m in enumerate(history) if m.user_id == self.bot_user_id]
        drop = set(own[:-OWN_LINES_IN_HISTORY]) if len(own) > OWN_LINES_IN_HISTORY else set()
        return [m for i, m in enumerate(history) if i not in drop]

    def _recent_own(self, chat_id: int) -> list[str]:
        rows = self.store.conn.execute(
            "SELECT text FROM messages WHERE chat_id=? AND user_id=? ORDER BY rowid DESC LIMIT ?",
            (chat_id, self.bot_user_id, RECENT_OWN_N)).fetchall()
        return [r[0] for r in rows]

    def vocabulary(self) -> set[str]:
        """Words the group itself uses (members only, never Botucha, never a private chat), plus slang and names."""
        words: set[str] = set()
        for (text,) in self.store.conn.execute(
                "SELECT text FROM messages WHERE is_bot=0 AND user_id != ? AND chat_id < 0", (self.bot_user_id,)):
            # caption only: a [nuotrauka: …] description is Botucha's wording, not the group's
            words.update(w.lower() for w in re.findall(r"[^\W\d_]+", caption_of(text) if text.startswith("[nuotrauka") else text))
        for t in self.memory.all_slang():
            words.update(w.lower() for w in re.findall(r"[^\W\d_]+", t.split("=", 1)[0]))
        for mem in self.store.members().values():
            words.update(w.lower() for w in re.findall(r"[^\W\d_]+", f"{mem.name} {mem.username or ''}"))
        # what he was told: people and their word forms, and facts a person wrote (never the model's own wording)
        for p in self.memory.people():
            words.update(w.lower() for t in [p.name, *p.aliases] for w in re.findall(r"[^\W\d_]+", t))
        for (text,) in self.store.conn.execute("SELECT text FROM facts WHERE kind='fact' AND source != 'auto'"):
            words.update(w.lower() for w in re.findall(r"[^\W\d_]+", text))
        words.update({"botucha", "botuchos", "xd", "xdd", "xddd", "xdddd"})
        words.update(known_words(self.store))  # approved on the dashboard (e.g. slang Claude judged real)
        return words

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
        last = self.store.get_message(chat_id, jobs[-1].msg_id)
        trigger = "+".join(dict.fromkeys(j.trigger for j in jobs if j.trigger))
        run = (self.tracer.start("reply", chat_id=chat_id, msg_id=jobs[-1].msg_id,
                                 user_name=last.name if last else None, trigger=trigger)
               if self.tracer else NULL_RUN)
        result, hits = None, []
        try:
            try:  # one request's worth: a backlog is the learning loop's job, not this reply's
                await self.memory.index_new_chunks(chat_id, limit=EMBED_BATCH)
            except Exception as e:
                log.warning("chunk indexing failed, replying without it: %s", e)
            ids = {j.msg_id for j in jobs}
            with run.step("context") as st:
                recent = self.store.recent_messages(chat_id, HISTORY_N)
                # commands are not conversation, except the /rimtai or /atsimeni being answered right now
                convo = [m for m in recent if not m.text.startswith("/") or m.msg_id in ids]
                history = self._trim_own(convo)
                st.detail.update(history=len(history), own_dropped=len(convo) - len(history))
                if not self.vision:
                    await self._has_vision()
                image_msg = self._pick_image(chat_id, jobs)
                image = await self._fetch_image(image_msg, st.detail) if image_msg else None
            # a photo's tag is not what anyone is talking about: search by captions and words only
            query = "\n".join(caption_of(m.text) for m in history if m.msg_id in ids).strip() \
                or (caption_of(history[-1].text) if history else "")
            with run.step("retrieval") as st:
                scored = []
                try:
                    hits = await self.memory.search_chunks(query, k=6 if recall else 3, chat_id=chat_id) if query else []
                    scored = await self.memory.search_facts_scored(query, k=5) if query else []
                except Exception as e:  # the embedding model is down: an answer without memory beats no answer
                    log.warning("memory search failed, replying without it: %s", e)
                    hits, scored = [], []
                    st.status = "error"
                    st.detail["error"] = f"{type(e).__name__}: {e}"
                facts = [f for f, _, _ in scored]
                prices = [format_quote(q) for q in await self.prices.quotes(detect_symbols(query, self.aliases))] \
                    if self.prices else []
                st.detail.update(
                    query=query[:300],
                    chunks=[{"first_msg_id": h.chunk.first_msg_id, "preview": h.chunk.text[:120],
                             "score": round(h.score, 4), "fts": h.fts} for h in hits],
                    facts=[{"id": f.id, "preview": f.text[:120], "score": round(sc, 4), "fts": fts}
                           for f, sc, fts in scored],
                    prices=prices)
            members = self.store.members()
            ctx = PromptContext(
                persona=_read(self.cfg.paths.persona), style_examples=_read(self.cfg.paths.style_examples),
                profiles={members[u].name: p for u, p in self.memory.profiles().items() if u in members},
                slang=self.memory.all_slang(), people=self.memory.people_lines(),
                chunks=[h.chunk.text for h in hits], facts=[f.text for f in facts], history=history,
                bot_user_id=self.bot_user_id, serious=any(j.serious for j in jobs), prices=prices, image=image,
                spelling_notes=spelling_notes(self.store))
            await self.outbox.typing(chat_id)
            result = await generate_reply_ex(self.llm, ctx, num_predict=self.cfg.model.num_predict,
                                             max_chars=self.cfg.model.num_ctx * 3,
                                             member_names=self._member_names(), speller=self.speller,
                                             recent_own=self._recent_own(chat_id), run=run,
                                             proofread=self.proofreader, direct=bool(direct))
        except Exception as e:
            log.exception("reply preparation failed")
            self.last_error = f"{type(e).__name__}: {e}"
            run.finish("error", error=self.last_error)
            if direct:
                await self._send(chat_id, [CANNED], direct[-1].msg_id, store=False)
            return
        texts = result.texts
        if texts is None and result.quiet:
            run.finish("skipped", error="stayed quiet: the uninvited reply had flagged words")
            return
        if texts is None:
            self.last_error = self.last_error or "model returned nothing"
            run.finish("canned" if direct else "skipped", error="no usable reply: every attempt failed or was rejected")
            if direct:
                await self._send(chat_id, [CANNED], direct[-1].msg_id, store=False)
            return
        if links and hits:
            texts = texts + [" ".join(message_link(h.chunk.chat_id, h.chunk.first_msg_id) for h in hits[:3])]
        with run.step("send") as st:
            sent = await self._send(chat_id, texts, direct[-1].msg_id if direct else None, store=True)
            st.detail["msg_ids"] = sent
            if len(sent) < len(texts):  # _send logs and stops at the first Telegram error
                st.status = "error"
                st.detail["error"] = self.last_error
        if not sent:
            run.finish("error", reply="\n".join(texts), error=self.last_error)
            return
        run.finish("fallback" if result.fallback else "sent", reply="\n".join(texts),
                   sent=[(chat_id, mid) for mid in sent])
        if image is not None and image_msg is not None and result.image_used \
                and not description_of(image_msg.text):  # already described: don't redo it
            await self._describe(chat_id, image_msg, image)

    # ---- images ----------------------------------------------------------
    def _pick_image(self, chat_id: int, jobs: list[Job]) -> StoredMessage | None:
        """At most one image per reply: a photo one of the answered messages replies to; otherwise the newest
        photo posted in the last IMAGE_WINDOW_S up to the answered message (albums, "photo, then ask")."""
        if not self.vision:
            return None
        answered = [m for j in jobs if (m := self.store.get_message(chat_id, j.msg_id))]
        for m in reversed(answered):
            parent = self.store.get_message(chat_id, m.reply_to) if m.reply_to else None
            if parent and parent.image_file_id:
                return parent
        if not answered:
            return None
        newest = max(answered, key=lambda m: m.ts)
        for m in reversed(self.store.recent_messages(chat_id, HISTORY_N)):
            if m.user_id == self.bot_user_id or m.is_bot:
                break  # he already answered everything before his own last line
            if m.image_file_id and newest.ts - IMAGE_WINDOW_S <= m.ts <= newest.ts + IMAGE_WINDOW_S:
                return m
        return None

    async def _has_vision(self) -> bool:
        """Startup can race Ollama: re-ask at most every VISION_RECHECK_S until it answers."""
        if self.vision or self.vision_check is None:
            return self.vision
        now = self.clock()
        if now - self._vision_checked_at < VISION_RECHECK_S:
            return False
        self._vision_checked_at = now
        found = await self.vision_check()
        if found is not None:
            self.vision = found
            log.info("vision: %s", "yes" if found else "no")
        return self.vision

    async def _fetch_image(self, msg: StoredMessage, detail: dict) -> bytes | None:
        """Download into memory only; on any problem the reply goes on without the image."""
        try:
            data = await asyncio.wait_for(self.outbox.fetch_image(msg.image_file_id), FETCH_TIMEOUT_S)
            if len(data) > MAX_IMAGE_BYTES:
                raise ValueError(f"image too large ({len(data)} bytes)")
        except Exception as e:
            log.warning("image download failed: %s", e)
            detail["image"] = {"msg_id": msg.msg_id, "error": f"{type(e).__name__}: {e}"}
            return None
        detail["image"] = {"msg_id": msg.msg_id, "bytes": len(data)}
        return data

    async def _describe(self, chat_id: int, msg: StoredMessage, image: bytes) -> None:
        """After the reply: a short description replaces the bare [nuotrauka] tag, so the image becomes memory."""
        run = self.tracer.start("describe", chat_id=chat_id, msg_id=msg.msg_id, user_name=msg.name,
                                trigger="image") if self.tracer else NULL_RUN
        try:
            with run.step("generation", "attempt 1") as st:
                res = await asyncio.wait_for(
                    chat_ex(self.llm, [{"role": "system", "content": IMAGE_GUARD},
                                       {"role": "user", "content": DESCRIBE_PROMPT}],
                            num_predict=DESCRIBE_NUM_PREDICT, images=[image]),
                    DESCRIBE_TIMEOUT_S)
                st.detail.update(res.stats)
                st.detail["raw"] = res.text
            desc = clean_description(res.text)
            if desc and self.speller and self.speller.unknown([desc]):
                desc = None  # invented words would end up in memory as if someone wrote them
            run.add_step("filter", name="attempt 1", status="ok" if desc else "rejected",
                         detail={"checks": [{"name": "description", "ok": bool(desc),
                                             "reason": "" if desc else "empty, command, instruction or foreign script"}]})
        except Exception as e:
            log.warning("image description failed: %s", e)
            run.finish("error", error=f"{type(e).__name__}: {e}")
            return
        if not desc:
            run.finish("skipped", error="description rejected")
            return
        current = self.store.get_message(chat_id, msg.msg_id)
        text = described_text(desc, caption_of(current.text if current else msg.text))
        self.store.update_message_text(chat_id, msg.msg_id, text)
        run.finish("sent", reply=text)

    async def _send(self, chat_id: int, texts: list[str], reply_to: int | None, *, store: bool) -> list[int]:
        out: list[int] = []
        for i, text in enumerate(texts):
            if i:
                await self.outbox.typing(chat_id)
                await self.sleep(self.rng.uniform(1.0, 2.0))
            try:
                sent = await self.outbox.send(chat_id, [text], reply_to if i == 0 else None)
            except Exception as e:
                log.warning("send failed: %s", e)
                self.last_error = f"send: {e}"
                return out
            out.extend(sent)
            if store and not text.startswith("https://t.me/"):
                for mid in sent:
                    self.store.add_message(StoredMessage(chat_id, mid, self.bot_user_id, BOT_NAME, self.clock(),
                                                         text, None, True))
        return out

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
            if is_private(chat_id):
                continue  # not the group's memory: no facts, slang or profile lines come from a private chat
            last = self.store.recent_messages(chat_id, 1)
            if not last:
                continue
            key = f"learned_rowid:{chat_id}"
            new = self.store.last_rowid(chat_id) - int(self.store.get_state(key, "0"))
            if not should_learn(now=self.clock(), last_msg_ts=last[0].ts, new_msgs=new,
                                reply_pending=self.worker.pending):
                continue
            await self.memory.index_new_chunks(chat_id, force=True)
            run = self.tracer.start("learn", chat_id=chat_id, trigger="idle") if self.tracer else NULL_RUN
            try:
                # a bounded piece of the backlog, and none of it while someone waits for a reply
                n = await learn_once(self.memory, self.llm, chat_id, locked=self._locked, run=run,
                                     max_calls=LEARN_MAX_CALLS, should_stop=lambda: self.worker.pending)
            except Exception as e:
                run.finish("error", error=f"{type(e).__name__}: {e}")
                raise
            run.finish("sent" if n else "skipped", reply=f"{n} new")
            if unlearned(self.memory, chat_id):
                continue  # more to read: the next tick goes on from the cursor
            self.store.set_state(key, str(self.store.last_rowid(chat_id)))
            if profiles_due(self.store, chat_id):
                await refresh_profiles(self.memory, self.llm, self.store, chat_id, locked=self._locked)

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
        stalled = 0  # a chunk the model cannot read is tried twice and then skipped, so this always ends
        while unlearned(self.memory, chat_id) and stalled < 2:
            before = self.store.get_state(f"learn_cursor:{chat_id}", "0")
            await learn_once(self.memory, self.llm, chat_id, locked=self._locked)
            stalled = stalled + 1 if self.store.get_state(f"learn_cursor:{chat_id}", "0") == before else 0
        await refresh_profiles(self.memory, self.llm, self.store, chat_id, locked=self._locked)
        self.store.set_state(f"learned_rowid:{chat_id}", str(self.store.last_rowid(chat_id)))
        self.store.set_state("export_imported", "1")
