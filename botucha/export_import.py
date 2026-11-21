"""Load a Telegram Desktop JSON export (result.json) into the store."""
from __future__ import annotations

import json
from pathlib import Path

from .store import Store, StoredMessage


def entity_text(t: object) -> str:
    """Export `text` is either a string or a list of strings and entity dicts."""
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        return "".join(x if isinstance(x, str) else str(x.get("text", "")) for x in t)
    return ""


def _user_id(from_id: str | None) -> int | None:
    if not from_id:
        return None
    digits = "".join(ch for ch in from_id if ch.isdigit())
    return int(digits) if digits else None


PRIVATE_TYPES = {"personal_chat", "bot_chat", "saved_messages"}


def _chat_id(d: dict) -> int:
    """The Bot API id of the exported chat: -100… for supergroups, the user's own id for a private chat."""
    raw = int(d["id"])
    if d.get("type", "").endswith("supergroup") or d.get("type") == "public_channel":
        return int(f"-100{raw}")
    if d.get("type") in PRIVATE_TYPES:
        return raw
    return -raw


def parse_export(path: Path) -> tuple[int, list[StoredMessage]]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    chat_id = _chat_id(d)
    out: list[StoredMessage] = []
    for m in d.get("messages", []):
        if m.get("type") != "message":
            continue
        uid = _user_id(m.get("from_id"))
        if uid is None:
            continue
        out.append(StoredMessage(
            chat_id=chat_id, msg_id=int(m["id"]), user_id=uid, name=m.get("from") or str(uid),
            ts=float(m["date_unixtime"]), text=entity_text(m.get("text", "")),
            reply_to=m.get("reply_to_message_id")))
    out.sort(key=lambda m: (m.ts, m.msg_id))
    return chat_id, out


def import_export(store: Store, path: Path) -> int:
    _, msgs = parse_export(path)
    added = 0
    for m in msgs:
        store.upsert_member(m.user_id, m.name, None)
        added += store.add_message(m)
    return added
