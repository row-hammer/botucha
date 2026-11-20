"""Build the prompt, call the model, clean the reply."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .chunking import render_line
from .llm import LLM
from .store import StoredMessage

log = logging.getLogger(__name__)

REPLY_INSTRUCTION = "atsakyk kaip botucha i paskutines zinutes"
SERIOUS_LINE = ("RIMTAI REZIMAS DABAR IJUNGTAS: sita karta atsakyk kaip tikras finansu ekspertas. "
                "2-6 trumpi sakiniai, faktiskai teisingai ir konkreciai (skaiciai, taisykles, rizikos), "
                "be bajeriu, be degeno patarimu, be kalbu apie save. Rasyk taisyklinga lietuviu kalba su lietuviskomis raidemis.")
MAX_LINES = 3
SERIOUS_MAX_LINES = 8
SERIOUS_NUM_PREDICT = 450


@dataclass
class PromptContext:
    persona: str
    style_examples: str
    profiles: dict[str, str]
    slang: list[str]
    chunks: list[str]
    facts: list[str]
    history: list[StoredMessage]
    bot_user_id: int
    serious: bool = False


def _system(ctx: PromptContext) -> str:
    """Stable parts first so Ollama can reuse the cached prefix."""
    parts = [ctx.persona.strip()]
    if ctx.serious:
        parts.append(SERIOUS_LINE)  # no style examples: they pull answers back to 5-word banter
    else:
        parts.append("Kaip grupe raso (tikri pavyzdziai):\n" + ctx.style_examples.strip())
    if ctx.profiles:
        parts.append("Grupes nariai:\n" + "\n".join(f"- {n}: {p}" for n, p in ctx.profiles.items()))
    if ctx.slang:
        parts.append("Slengas:\n" + "\n".join(ctx.slang))
    if ctx.chunks:
        parts.append("Ka prisimeni is senu pokalbiu:\n" + "\n---\n".join(ctx.chunks))
    if ctx.facts:
        parts.append("Ka zinai:\n" + "\n".join(f"- {f}" for f in ctx.facts))
    return "\n\n".join(parts)


def _line(m: StoredMessage, bot_id: int) -> str:
    if m.user_id == bot_id or m.is_bot:
        return "botucha: " + " ".join(m.text.split())
    return render_line(m)


def build_prompt(ctx: PromptContext, *, max_chars: int) -> list[dict]:
    system = _system(ctx)
    tail = REPLY_INSTRUCTION + ("\n" + SERIOUS_LINE if ctx.serious else "")
    lines = [_line(m, ctx.bot_user_id) for m in ctx.history]
    if lines and len(lines[-1]) > max_chars // 4:
        lines[-1] = lines[-1][: max_chars // 4]
    budget = max_chars - len(system) - len(tail) - 2
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        if kept and used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    user = "\n".join(reversed(kept)) + "\n\n" + tail
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


_MD = re.compile(r"[*_`]")
ROLE_LABELS = {"assistant", "bot", "user", "system", "ai", "eval"}


def _squash(s: str) -> str:
    return re.sub(r"\W", "", s.lower())


def clean_reply(raw: str, member_names: list[str], max_lines: int = MAX_LINES) -> list[str]:
    names = {_squash(n) for n in member_names if n}
    out: list[str] = []
    for line in raw.splitlines():
        line = _MD.sub("", line).strip()
        line = re.sub(r"^[-•]\s+", "", line)
        m = re.match(r"^([^:]{1,32}?):\s*(.*)$", line)
        if m:
            who = _squash(m.group(1))
            if who in ROLE_LABELS or any(who and n.startswith(who) for n in names):
                continue  # model wrote as a real member or leaked a chat-format label
            if who.startswith("botuch"):
                line = m.group(2)
        line = line.strip().strip('"„“”\'').strip()
        if line:
            out.append(line)
    return out[:max_lines]


LT_LETTERS = set("ąčęėįšųūžĄČĘĖĮŠŲŪŽ")


def _foreign_char(c: str) -> bool:
    """A letter that is neither ASCII, Lithuanian nor Cyrillic (the group writes Russianisms)."""
    return c.isalpha() and not (c.isascii() or c in LT_LETTERS or "\u0400" <= c <= "\u04ff")


def has_foreign_script(text: str) -> bool:
    return any(_foreign_char(c) for c in text)


def strip_foreign(texts: list[str]) -> list[str]:
    out = [" ".join(w for w in t.split() if not has_foreign_script(w)) for t in texts]
    return [t for t in out if t]


async def generate_reply(llm: LLM, ctx: PromptContext, *, num_predict: int, max_chars: int,
                         member_names: list[str]) -> list[str] | None:
    messages = build_prompt(ctx, max_chars=max_chars)
    if ctx.serious:
        num_predict = max(num_predict, SERIOUS_NUM_PREDICT)
    max_lines = SERIOUS_MAX_LINES if ctx.serious else MAX_LINES
    fallback: list[str] | None = None
    for attempt in range(2):
        try:
            texts = clean_reply(await llm.chat(messages, num_predict=num_predict), member_names, max_lines)
        except Exception as e:  # model down, timeout, bad response
            log.warning("generation failed (attempt %d): %s", attempt + 1, e)
            continue
        if texts and any(has_foreign_script(t) for t in texts):
            fallback = strip_foreign(texts) or fallback  # model glitch: stray Hindi/Arabic/Turkish words
            continue
        if texts:
            return texts
    return fallback or None
