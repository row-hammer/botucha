"""Cut a message stream into conversation windows: the unit of chat memory.

A lone "xdd" is useless to search; 10-15 consecutive lines carry the actual exchange.
"""
from __future__ import annotations

from dataclasses import dataclass

from .store import StoredMessage


@dataclass
class Chunk:
    chat_id: int
    first_msg_id: int
    last_msg_id: int
    start_ts: float
    end_ts: float
    text: str


def render_line(m: StoredMessage) -> str:
    text = " ".join(m.text.split()) or "[media]"
    return f"{m.name}: {text}"


def _close(group: list[StoredMessage], lines: list[str]) -> Chunk:
    return Chunk(group[0].chat_id, group[0].msg_id, group[-1].msg_id, group[0].ts, group[-1].ts, "\n".join(lines))


def build_chunks(msgs: list[StoredMessage], gap_s: int = 1800, max_msgs: int = 15,
                 max_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    group: list[StoredMessage] = []
    lines: list[str] = []
    size = 0
    for m in msgs:
        line = render_line(m)
        if group and (m.ts - group[-1].ts > gap_s or len(group) >= max_msgs
                      or size + 1 + len(line) > max_chars):
            chunks.append(_close(group, lines))
            group, lines, size = [], [], 0
        size += len(line) + (1 if group else 0)
        group.append(m)
        lines.append(line)
    if group:
        chunks.append(_close(group, lines))
    return chunks
