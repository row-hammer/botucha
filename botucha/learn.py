"""Idle-time learning: pull facts and slang out of new chunks, refresh member profiles."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .guard import MAX_FACT_CHARS, MAX_SLANG_CHARS, looks_like_instruction
from .llm import LLM
from .memory import Memory
from .store import Store

log = logging.getLogger(__name__)

BOT_LINE_PREFIX = "Botucha:"

EXTRACT_PROMPT = (
    "Tu skaitai lietuviu draugu Telegram grupes pokalbi. Isrink NAUJUS faktus apie grupes narius "
    "(kuo investuoja, ka dirba, iprociai, vidiniai bajeriai, kas ka sake svarbaus) ir slengo zodzius su ju "
    "reiksmemis. Faktus rasyk trumpai, vienu sakiniu, lietuviskai, ir kiekviena fakta pradek zmogaus vardu. Jei nieko naujo nera, grazink tuscius "
    "sarasus. Atsakyk TIK JSON: "
    '{"facts": [{"about": "nario vardas arba null", "text": "faktas"}], '
    '"slang": [{"word": "zodis", "meaning": "reiksme"}]}'
)
PROFILE_PROMPT = (
    "Parasyk trumpa (5-10 eiluciu) profili apie grupes nari {name}: kuo jis investuoja, kaip kalba, "
    "ka megsta, jo iprociai ir vidiniai bajeriai. Tik faktai is duomenu, be ivado.\n\n"
    "Zinomi faktai:\n{facts}\n\nJo paskutines zinutes:\n{lines}"
)


@dataclass
class Extraction:
    facts: list[tuple[str | None, str]]
    slang: list[tuple[str, str]]


def parse_extraction(raw: str) -> Extraction | None:
    try:
        d = json.loads(raw)
        facts = [(f.get("about") or None, str(f.get("text") or "").strip()) for f in d.get("facts", [])]
        slang = [(str(s.get("word") or "").strip(), str(s.get("meaning") or "").strip()) for s in d.get("slang", [])]
    except (ValueError, AttributeError, TypeError):
        return None
    return Extraction([(a, t) for a, t in facts if t], [(w, m) for w, m in slang if w and m])


def should_learn(*, now: float, last_msg_ts: float, new_msgs: int, reply_pending: bool,
                 idle_s: int = 600, min_new: int = 30) -> bool:
    return not reply_pending and new_msgs >= min_new and now - last_msg_ts >= idle_s


def resolve_member(about: str | None, store: Store) -> int | None:
    if not about:
        return None
    a = str(about).lower().lstrip("@")
    for m in store.members().values():
        if m.name.lower().startswith(a) or (m.username and m.username.lower().startswith(a)):
            return m.user_id
    return None


async def learn_once(memory: Memory, llm: LLM, chat_id: int, *, source: str = "auto",
                     locked: frozenset[int] = frozenset()) -> int:
    key = f"learn_cursor:{chat_id}"
    cursor = int(memory.store.get_state(key, "0"))
    new = memory.chunks_after(chat_id, cursor)
    if not new:
        return 0
    # Botucha's own lines are not the group's language: learning from them would feed his jokes back to him.
    text = "\n---\n".join("\n".join(l for l in c.text.splitlines() if not l.startswith(BOT_LINE_PREFIX))
                          for _, c in new)
    raw = await llm.chat([{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": text}],
                         num_predict=800, fmt_json=True)
    ext = parse_extraction(raw)
    if ext is None:
        log.warning("learning: model returned invalid JSON, skipping this run")
        return 0
    n = 0
    for about, fact in ext.facts:
        if len(fact) > MAX_FACT_CHARS or looks_like_instruction(fact):
            log.warning("learning: skipped instruction-like fact: %.80s", fact)
            continue
        uid = resolve_member(about, memory.store)
        person = memory.find_person(about) if about and uid is None else None
        if person and person.id not in {p.id for p in memory.people_in(fact)}:
            fact = f"{person.name} – {fact[:1].lower()}{fact[1:]}"  # keep who it is about inside the text
        if uid in locked:
            continue  # owner keeps this member's memory by hand
        await memory.upsert_fact("fact", fact, uid, source)
        n += 1
    for word, meaning in ext.slang:
        if len(word) + len(meaning) > MAX_SLANG_CHARS or looks_like_instruction(f"{word} {meaning}"):
            continue
        await memory.upsert_fact("slang", f"{word.lower()} = {meaning}", None, source)
        n += 1
    memory.store.set_state(key, str(new[-1][0]))
    return n


def profiles_due(store: Store, chat_id: int, every: int = 200) -> bool:
    done = int(store.get_state(f"profiles_rowid:{chat_id}", "0"))
    return store.last_rowid(chat_id) - done >= every


async def refresh_profiles(memory: Memory, llm: LLM, store: Store, chat_id: int,
                           locked: frozenset[int] = frozenset()) -> None:
    for uid, member in sorted(store.members().items()):
        if uid in locked:
            continue
        rows = store.conn.execute(
            "SELECT name, text FROM messages WHERE chat_id=? AND user_id=? AND text != '' "
            "ORDER BY rowid DESC LIMIT 50", (chat_id, uid)).fetchall()
        if not rows:
            continue
        facts = "\n".join(f"- {f.text}" for f in memory.facts_about(uid)) or "-"
        lines = "\n".join(t for _, t in reversed(rows))
        prompt = PROFILE_PROMPT.format(name=member.name, facts=facts, lines=lines)
        text = (await llm.chat([{"role": "user", "content": prompt}], num_predict=300)).strip()
        if text:
            memory.set_profile(uid, text)
    store.set_state(f"profiles_rowid:{chat_id}", str(store.last_rowid(chat_id)))
