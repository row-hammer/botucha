"""When Botucha speaks: pure decision logic, no I/O."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .config import TriggerCfg

RECALL_RE = re.compile(r"\b(atsimen\w*|pamen\w*|prisimen\w*|kai mes)\b", re.IGNORECASE)


class Decision(Enum):
    REPLY = "reply"
    REACT = "react"
    NONE = "none"


@dataclass
class TriggerState:
    enabled: bool = True
    random_n: int = 25
    quiet_until: float = 0.0
    last_unsolicited: float = 0.0


class _Rng(Protocol):
    def random(self) -> float: ...


def fold(text: str) -> str:
    """Lowercase and strip diacritics (ą -> a, š -> s)."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def is_direct(text: str, *, reply_to_bot: bool, mentions_bot: bool, name_regex: str) -> bool:
    return reply_to_bot or mentions_bot or re.search(name_regex, fold(text)) is not None


def is_recall(text: str) -> bool:
    return RECALL_RE.search(fold(text)) is not None


def has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    words = re.findall(r"\w+", fold(text))
    return any(w.startswith(k) for w in words for k in keywords)


def decide(text: str, *, sender_is_bot: bool, direct: bool, started_at: float, msg_ts: float, now: float,
           state: TriggerState, cfg: TriggerCfg, rng: _Rng) -> Decision:
    if sender_is_bot or not text.strip() or msg_ts < started_at or not state.enabled:
        return Decision.NONE
    if direct:
        return Decision.REPLY
    if now < state.quiet_until or now - state.last_unsolicited < cfg.cooldown_s:
        return Decision.NONE
    if has_keyword(text, cfg.keywords) and rng.random() < cfg.keyword_prob:
        return Decision.REPLY
    if rng.random() < 1 / max(state.random_n, 1):
        return Decision.REPLY
    if rng.random() < 1 / max(cfg.reaction_n, 1):
        return Decision.REACT
    return Decision.NONE


def mark_unsolicited(state: TriggerState, now: float) -> None:
    state.last_unsolicited = now
