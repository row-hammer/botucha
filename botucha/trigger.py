"""When Botucha speaks: pure decision logic, no I/O."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .config import TriggerCfg
from .text import fold  # noqa: F401  (re-exported: many modules import fold from here)

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


def is_direct(text: str, *, reply_to_bot: bool, mentions_bot: bool, name_regex: str) -> bool:
    return reply_to_bot or mentions_bot or re.search(name_regex, fold(text), re.IGNORECASE) is not None


def is_recall(text: str) -> bool:
    return RECALL_RE.search(fold(text)) is not None


def matched_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
    words = re.findall(r"\w+", fold(text))
    return next((k for w in words for k in keywords if w.startswith(k)), None)


def has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return matched_keyword(text, keywords) is not None


def decide_with_reason(text: str, *, sender_is_bot: bool, direct: bool, started_at: float, msg_ts: float,
                       now: float, state: TriggerState, cfg: TriggerCfg, rng: _Rng) -> tuple[Decision, str]:
    if sender_is_bot or not text.strip() or msg_ts < started_at or not state.enabled:
        return Decision.NONE, ""
    if direct:
        return Decision.REPLY, "direct"
    if now < state.quiet_until or now - state.last_unsolicited < cfg.cooldown_s:
        return Decision.NONE, ""
    kw = matched_keyword(text, cfg.keywords)
    if kw and rng.random() < cfg.keyword_prob:
        return Decision.REPLY, f"keyword:{kw}"
    if rng.random() < 1 / max(state.random_n, 1):
        return Decision.REPLY, f"random:1/{state.random_n}"
    if rng.random() < 1 / max(cfg.reaction_n, 1):
        return Decision.REACT, "reaction"
    return Decision.NONE, ""


def decide(text: str, *, sender_is_bot: bool, direct: bool, started_at: float, msg_ts: float, now: float,
           state: TriggerState, cfg: TriggerCfg, rng: _Rng) -> Decision:
    return decide_with_reason(text, sender_is_bot=sender_is_bot, direct=direct, started_at=started_at,
                              msg_ts=msg_ts, now=now, state=state, cfg=cfg, rng=rng)[0]


def mark_unsolicited(state: TriggerState, now: float) -> None:
    state.last_unsolicited = now
