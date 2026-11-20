"""Map Telegram reactions on Botucha's messages to good/bad feedback."""
from __future__ import annotations

POSITIVE = {"👍", "❤", "🔥", "🤣", "😁", "💯", "🏆", "👏", "😍", "🥰"}
NEGATIVE = {"👎", "💩", "🤮", "😴", "🥱"}


def _norm(e: str) -> str:
    return e.replace("️", "")


def score_for_reactions(emojis: list[str]) -> int | None:
    """+1 good, -1 bad (any bad reaction wins), None when no reaction carries a judgement."""
    es = {_norm(e) for e in emojis}
    if es & NEGATIVE:
        return -1
    if es & POSITIVE:
        return 1
    return None
