"""SQLite storage: schema, members, messages, key/value state."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    rowid INTEGER PRIMARY KEY,
    chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    name TEXT NOT NULL, ts REAL NOT NULL, text TEXT NOT NULL, reply_to INTEGER,
    is_bot INTEGER NOT NULL DEFAULT 0,
    UNIQUE (chat_id, msg_id)
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL,
    first_msg_id INTEGER NOT NULL, last_msg_id INTEGER NOT NULL,
    start_ts REAL NOT NULL, end_ts REAL NOT NULL, text TEXT NOT NULL, emb BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id');
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('fact', 'slang')),
    text TEXT NOT NULL, about INTEGER, source TEXT NOT NULL,
    created REAL NOT NULL, updated REAL NOT NULL, emb BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, content='facts', content_rowid='id');
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY, text TEXT NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    aliases TEXT NOT NULL DEFAULT '', user_id INTEGER
);
CREATE TABLE IF NOT EXISTS fact_people (
    fact_id INTEGER NOT NULL, person_id INTEGER NOT NULL, PRIMARY KEY (fact_id, person_id)
);
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY, a INTEGER NOT NULL, rel TEXT NOT NULL, b INTEGER NOT NULL,
    source TEXT NOT NULL, created REAL NOT NULL, UNIQUE (a, rel, b)
);
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, chat_id INTEGER, msg_id INTEGER, user_name TEXT,
    trigger TEXT NOT NULL DEFAULT '', outcome TEXT, error TEXT, reply TEXT,
    started REAL NOT NULL, duration_ms REAL
);
CREATE INDEX IF NOT EXISTS traces_started ON traces (started);
CREATE TABLE IF NOT EXISTS trace_steps (
    id INTEGER PRIMARY KEY, trace_id INTEGER NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT,
    status TEXT NOT NULL, started REAL NOT NULL, duration_ms REAL NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
    prompt TEXT
);
CREATE INDEX IF NOT EXISTS trace_steps_trace ON trace_steps (trace_id);
CREATE TABLE IF NOT EXISTS trace_messages (
    trace_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, PRIMARY KEY (chat_id, msg_id)
);
CREATE TABLE IF NOT EXISTS feedback (
    chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    score INTEGER NOT NULL, reason TEXT, ts REAL NOT NULL,
    PRIMARY KEY (chat_id, msg_id, user_id)
);
CREATE TABLE IF NOT EXISTS corrections (
    chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    text TEXT NOT NULL, ts REAL NOT NULL,
    PRIMARY KEY (chat_id, msg_id, user_id)
);
"""


@dataclass
class StoredMessage:
    chat_id: int
    msg_id: int
    user_id: int
    name: str
    ts: float
    text: str
    reply_to: int | None = None
    is_bot: bool = False


@dataclass
class BadFeedback:
    chat_id: int
    msg_id: int
    user_id: int
    text: str
    reason: str | None
    ts: float


@dataclass
class Correction:
    chat_id: int
    msg_id: int
    user_id: int
    original: str
    text: str
    ts: float


@dataclass
class Member:
    user_id: int
    name: str
    username: str | None


_COLS = "chat_id, msg_id, user_id, name, ts, text, reply_to, is_bot"


def _row(r: tuple) -> StoredMessage:
    return StoredMessage(r[0], r[1], r[2], r[3], r[4], r[5], r[6], bool(r[7]))


class Store:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout=5000")  # the bot and the web service share this file
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.execute("PRAGMA user_version = 1")
        self.conn.commit()

    def _migrate(self) -> None:
        for table in ("feedback", "corrections"):
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if "reviewed" not in cols:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN reviewed INTEGER NOT NULL DEFAULT 0")

    def add_message(self, m: StoredMessage) -> bool:
        cur = self.conn.execute(
            f"INSERT OR IGNORE INTO messages ({_COLS}) VALUES (?,?,?,?,?,?,?,?)",
            (m.chat_id, m.msg_id, m.user_id, m.name, m.ts, m.text, m.reply_to, int(m.is_bot)))
        self.conn.commit()
        return cur.rowcount == 1

    def update_message_text(self, chat_id: int, msg_id: int, text: str) -> None:
        self.conn.execute("UPDATE messages SET text=? WHERE chat_id=? AND msg_id=?", (text, chat_id, msg_id))
        self.conn.commit()

    def recent_messages(self, chat_id: int, n: int) -> list[StoredMessage]:
        rows = self.conn.execute(
            f"SELECT {_COLS} FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT ?", (chat_id, n)).fetchall()
        return [_row(r) for r in reversed(rows)]

    def messages_after(self, chat_id: int, rowid: int) -> list[tuple[int, StoredMessage]]:
        rows = self.conn.execute(
            f"SELECT rowid, {_COLS} FROM messages WHERE chat_id=? AND rowid>? ORDER BY rowid",
            (chat_id, rowid)).fetchall()
        return [(r[0], _row(r[1:])) for r in rows]

    def last_rowid(self, chat_id: int) -> int:
        r = self.conn.execute("SELECT MAX(rowid) FROM messages WHERE chat_id=?", (chat_id,)).fetchone()
        return r[0] or 0

    def upsert_member(self, user_id: int, name: str, username: str | None) -> None:
        self.conn.execute(
            "INSERT INTO members (user_id, name, username) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name, "
            "username=COALESCE(excluded.username, members.username)", (user_id, name, username))
        self.conn.commit()

    def members(self) -> dict[int, Member]:
        return {r[0]: Member(*r) for r in self.conn.execute("SELECT user_id, name, username FROM members")}

    def get_message(self, chat_id: int, msg_id: int) -> StoredMessage | None:
        r = self.conn.execute(f"SELECT {_COLS} FROM messages WHERE chat_id=? AND msg_id=?", (chat_id, msg_id)).fetchone()
        return _row(r) if r else None

    # ---- feedback on Botucha's messages ------------------------------------
    def set_feedback(self, chat_id: int, msg_id: int, user_id: int, score: int, reason: str | None, ts: float) -> None:
        self.conn.execute(
            "INSERT INTO feedback (chat_id, msg_id, user_id, score, reason, ts) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(chat_id, msg_id, user_id) DO UPDATE SET score=excluded.score, reason=excluded.reason, "
            "ts=excluded.ts", (chat_id, msg_id, user_id, score, reason, ts))
        self.conn.commit()

    def clear_feedback(self, chat_id: int, msg_id: int, user_id: int) -> None:
        self.conn.execute("DELETE FROM feedback WHERE chat_id=? AND msg_id=? AND user_id=?", (chat_id, msg_id, user_id))
        self.conn.commit()

    def feedback_totals(self) -> tuple[int, int]:
        r = self.conn.execute("SELECT COALESCE(SUM(score>0),0), COALESCE(SUM(score<0),0) FROM feedback").fetchone()
        return int(r[0]), int(r[1])

    def recent_bad_feedback(self, n: int) -> list[BadFeedback]:
        rows = self.conn.execute(
            "SELECT f.chat_id, f.msg_id, f.user_id, m.text, f.reason, f.ts FROM feedback f "
            "JOIN messages m ON m.chat_id=f.chat_id AND m.msg_id=f.msg_id "
            "WHERE f.score<0 ORDER BY f.ts DESC LIMIT ?", (n,)).fetchall()
        return [BadFeedback(*r) for r in rows]

    def set_correction(self, chat_id: int, msg_id: int, user_id: int, text: str, ts: float) -> None:
        """A member's better version of one of Botucha's replies (fine-tuning data)."""
        self.conn.execute(
            "INSERT INTO corrections (chat_id, msg_id, user_id, text, ts) VALUES (?,?,?,?,?) "
            "ON CONFLICT(chat_id, msg_id, user_id) DO UPDATE SET text=excluded.text, ts=excluded.ts",
            (chat_id, msg_id, user_id, text, ts))
        self.conn.commit()

    def recent_corrections(self, n: int) -> list[Correction]:
        rows = self.conn.execute(
            "SELECT c.chat_id, c.msg_id, c.user_id, m.text, c.text, c.ts FROM corrections c "
            "JOIN messages m ON m.chat_id=c.chat_id AND m.msg_id=c.msg_id ORDER BY c.ts DESC LIMIT ?", (n,)).fetchall()
        return [Correction(*r) for r in rows]

    def get_state(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO state (key, value) VALUES (?,?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()
