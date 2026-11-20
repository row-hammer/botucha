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
SERIOUS_LINE = ("RIMTAI rezimas: atsakyk trumpai, aiskiai ir faktiskai teisingai, be teatro ir be bajeriu. "
                "Lengvas botuchos balsas tinka.")
MAX_LINES = 3


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
    parts = [ctx.persona.strip(), "Kaip grupe raso (tikri pavyzdziai):\n" + ctx.style_examples.strip()]
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


def clean_reply(raw: str, member_names: list[str]) -> list[str]:
    names = {n.lower() for n in member_names if n}
    out: list[str] = []
    for line in raw.splitlines():
        line = _MD.sub("", line).strip()
        line = re.sub(r"^[-•]\s+", "", line)
        m = re.match(r"^([^:\s]{1,32}):\s*(.*)$", line)
        if m:
            who = m.group(1).lower()
            if who in names:
                continue  # model wrote as a real member
            if who.startswith("botuch"):
                line = m.group(2)
        line = line.strip().strip('"„“”\'').strip()
        if line:
            out.append(line)
    return out[:MAX_LINES]


async def generate_reply(llm: LLM, ctx: PromptContext, *, num_predict: int, max_chars: int,
                         member_names: list[str]) -> list[str] | None:
    messages = build_prompt(ctx, max_chars=max_chars)
    for attempt in range(2):
        try:
            texts = clean_reply(await llm.chat(messages, num_predict=num_predict), member_names)
        except Exception as e:  # model down, timeout, bad response
            log.warning("generation failed (attempt %d): %s", attempt + 1, e)
            continue
        if texts:
            return texts
    return None
