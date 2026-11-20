"""Chat commands. Everyone: isimink, slengas, ka_zinai, tyla. Admin: pamirsk, taisyk, daznis, isjunk, ijunk, statusas.
rimtai and atsimeni are routed through the reply worker, so handle_command returns None for them."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config, TriggerCfg
from .learn import resolve_member
from .memory import Memory
from .store import Store
from .trigger import TriggerState

ADMIN_ONLY = {"pamirsk", "taisyk", "daznis", "isjunk", "ijunk", "statusas", "ivertinimai"}
NOT_ADMIN = "tik bosas gali"


@dataclass
class CommandContext:
    memory: Memory
    store: Store
    state: TriggerState
    cfg: Config
    started_at: float
    last_error: str | None
    chat_id: int


def parse_command(text: str, bot_username: str) -> tuple[str, str] | None:
    m = re.match(r"^/(\w+)(?:@(\w+))?(?:\s+(.*))?$", text.strip(), re.DOTALL)
    if not m:
        return None
    if m.group(2) and m.group(2).lower() != bot_username.lower():
        return None  # addressed to another bot
    return m.group(1).lower(), (m.group(3) or "").strip()


def message_link(chat_id: int, msg_id: int) -> str:
    return f"https://t.me/c/{abs(chat_id) - 10**12}/{msg_id}"


def load_trigger_state(store: Store, cfg: TriggerCfg) -> TriggerState:
    return TriggerState(enabled=store.get_state("enabled", "1") == "1",
                        random_n=int(store.get_state("random_n", str(cfg.random_n))))


def _int(s: str) -> int | None:
    try:
        return int(s.split()[0].lstrip("#"))
    except (ValueError, IndexError):
        return None


def _uptime(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    return f"{h} h {rem // 60} min"


async def handle_command(name: str, args: str, sender_id: int, now: float, ctx: CommandContext) -> str | None:
    if name in ADMIN_ONLY and sender_id != ctx.cfg.telegram.admin_id:
        return NOT_ADMIN
    mem, store = ctx.memory, ctx.store

    if name == "isimink":
        if not args:
            return "naudok: /isimink <faktas>"
        fid = await mem.add_fact("fact", args, None, f"cmd:{sender_id}")
        return f"isiminiau (#{fid})"

    if name == "slengas":
        word, sep, meaning = args.partition("=")
        if not sep or not word.strip() or not meaning.strip():
            return "naudok: /slengas <zodis> = <reiksme>"
        text = f"{word.strip().lower()} = {meaning.strip()}"
        fid = await mem.add_fact("slang", text, None, f"cmd:{sender_id}")
        return f"ok, {text} (#{fid})"

    if name == "ka_zinai":
        uid = resolve_member(args, store) if args else sender_id
        if uid is None:
            return "tokio nepazistu"
        member = store.members().get(uid)
        lines = [f"{member.name if member else uid}:"]
        profile = mem.profiles().get(uid)
        if profile:
            lines.append(profile)
        lines += [f"#{f.id} {f.text}" for f in mem.facts_about(uid)]
        return "\n".join(lines) if len(lines) > 1 else "apie ji nieko nezinau"

    if name == "tyla":
        minutes = _int(args) if args else ctx.cfg.trigger.tyla_default_min
        if minutes is None or minutes < 0:
            return "naudok: /tyla [minutes]"
        ctx.state.quiet_until = now + minutes * 60
        return f"ok, tyliu {minutes} min"

    if name == "pamirsk":
        fid = _int(args)
        if fid is None:
            return "naudok: /pamirsk <nr>"
        return f"pamirsau #{fid}" if mem.delete_fact(fid) else f"#{fid} nera"

    if name == "taisyk":
        fid, _, text = args.partition(" ")
        fid_n = _int(fid)
        if fid_n is None or not text.strip():
            return "naudok: /taisyk <nr> <naujas tekstas>"
        return f"pataisiau #{fid_n}" if await mem.update_fact(fid_n, text.strip()) else f"#{fid_n} nera"

    if name == "daznis":
        n = _int(args)
        if n is None or n < 2:
            return "naudok: /daznis <n>, n >= 2 (1 is n zinuciu)"
        ctx.state.random_n = n
        store.set_state("random_n", str(n))
        return f"ok, savo iniciatyva rasau ~1 is {n} zinuciu"

    if name in ("isjunk", "ijunk"):
        ctx.state.enabled = name == "ijunk"
        store.set_state("enabled", "1" if ctx.state.enabled else "0")
        return "ijungtas" if ctx.state.enabled else "isjungtas, bet viska girdziu"

    if name == "statusas":
        q = store.conn.execute
        msgs = q("SELECT COUNT(*) FROM messages").fetchone()[0]
        chunks = q("SELECT COUNT(*) FROM chunks").fetchone()[0]
        facts = q("SELECT COUNT(*) FROM facts").fetchone()[0]
        return "\n".join([
            f"modelis: {ctx.cfg.model.chat_model}",
            f"zinuciu: {msgs}, pokalbiu gabalu: {chunks}, faktu: {facts}",
            f"veikiu: {_uptime(now - ctx.started_at)}",
            f"ijungtas: {'taip' if ctx.state.enabled else 'ne'}, daznis 1/{ctx.state.random_n}",
            f"ivertinimai: 👍 {store.feedback_totals()[0]} / 👎 {store.feedback_totals()[1]}",
            f"paskutine klaida: {ctx.last_error or 'nera'}",
        ])

    if name == "ivertinimai":
        good, bad = store.feedback_totals()
        lines = [f"👍 {good} / 👎 {bad}"]
        recent = store.recent_bad_feedback(10)
        if recent:
            lines.append("paskutiniai blogi:")
            lines += [f"- {b.text}" + (f" — {b.reason}" if b.reason else "") for b in recent]
        return "\n".join(lines)

    return None
