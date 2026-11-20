"""Chat memory: conversation chunks, facts, slang and member profiles over SQLite."""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import numpy as np

from .chunking import Chunk, build_chunks
from .embed import Embedder
from .store import Store

GAP_S = 1800
DEDUPE_COS = 0.88
FactKind = Literal["fact", "slang"]


@dataclass
class Fact:
    id: int
    kind: FactKind
    text: str
    about: int | None
    source: str
    created: float
    updated: float


@dataclass
class ChunkHit:
    chunk: Chunk
    score: float


def _blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _vec(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def fts_query(text: str) -> str | None:
    """OR-join quoted word tokens so user text can never break FTS5 syntax."""
    words = [w for w in re.findall(r"\w+", text.lower()) if len(w) > 1]
    return " OR ".join(f'"{w}"' for w in words) if words else None


class Memory:
    def __init__(self, store: Store, embedder: Embedder, clock: Callable[[], float] = time.time):
        self.store = store
        self.db = store.conn
        self.embedder = embedder
        self.clock = clock
        self._index_lock = asyncio.Lock()

    # ---- chunks ---------------------------------------------------------
    async def index_new_chunks(self, chat_id: int, *, force: bool = False) -> int:
        async with self._index_lock:  # reply worker, learning and bootstrap may call this concurrently
            return await self._index_new_chunks(chat_id, force)

    async def _index_new_chunks(self, chat_id: int, force: bool) -> int:
        key = f"chunk_cursor:{chat_id}"
        cursor = int(self.store.get_state(key, "0"))
        rows = self.store.messages_after(chat_id, cursor)
        if not rows:
            return 0
        rowid_of = {m.msg_id: rid for rid, m in rows}
        chunks = build_chunks([m for _, m in rows], gap_s=GAP_S)
        if not force and chunks and self.clock() - chunks[-1].end_ts <= GAP_S:
            chunks = chunks[:-1]  # still open: more messages may join it
        if not chunks:
            return 0
        embs = await self.embedder.embed([c.text for c in chunks])
        for c, e in zip(chunks, embs):
            cur = self.db.execute(
                "INSERT INTO chunks (chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text, emb) "
                "VALUES (?,?,?,?,?,?,?)",
                (c.chat_id, c.first_msg_id, c.last_msg_id, c.start_ts, c.end_ts, c.text, _blob(e)))
            self.db.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?,?)", (cur.lastrowid, c.text))
        self.db.commit()
        self.store.set_state(key, str(rowid_of[chunks[-1].last_msg_id]))
        return len(chunks)

    def chunks_after(self, chat_id: int, chunk_id: int) -> list[tuple[int, Chunk]]:
        rows = self.db.execute(
            "SELECT id, chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text FROM chunks "
            "WHERE chat_id=? AND id>? ORDER BY id", (chat_id, chunk_id)).fetchall()
        return [(r[0], Chunk(*r[1:])) for r in rows]

    async def _hybrid(self, table: str, query: str, k: int, where: str = "", args: tuple = ()) -> list[tuple[int, float]]:
        """FTS top 10 ∪ cosine top 10, ranked by cosine. Returns (id, score)."""
        q = (await self.embedder.embed([query]))[0]
        rows = self.db.execute(f"SELECT id, emb FROM {table} {where}", args).fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        mat = np.stack([_vec(r[1]) for r in rows])
        scores = mat @ q
        cand = {ids[i] for i in np.argsort(-scores)[:10]}
        fq = fts_query(query)
        if fq:
            try:
                hits = self.db.execute(
                    f"SELECT rowid FROM {table}_fts WHERE {table}_fts MATCH ? ORDER BY rank LIMIT 10", (fq,))
                cand |= {r[0] for r in hits if r[0] in set(ids)}
            except Exception:
                pass
        score_of = dict(zip(ids, scores.tolist()))
        return sorted(((i, score_of[i]) for i in cand), key=lambda x: -x[1])[:k]

    # ---- facts and slang --------------------------------------------------
    async def add_fact(self, kind: FactKind, text: str, about: int | None, source: str) -> int:
        emb = (await self.embedder.embed([text]))[0]
        return self._insert_fact(kind, text, about, source, emb)

    def _insert_fact(self, kind, text, about, source, emb) -> int:
        now = self.clock()
        cur = self.db.execute(
            "INSERT INTO facts (kind, text, about, source, created, updated, emb) VALUES (?,?,?,?,?,?,?)",
            (kind, text, about, source, now, now, _blob(emb)))
        self.db.execute("INSERT INTO facts_fts (rowid, text) VALUES (?,?)", (cur.lastrowid, text))
        self.db.commit()
        return cur.lastrowid

    def _set_fact_text(self, fact_id: int, old: str, text: str, emb) -> None:
        self.db.execute("INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', ?, ?)", (fact_id, old))
        self.db.execute("UPDATE facts SET text=?, emb=?, updated=? WHERE id=?",
                        (text, _blob(emb), self.clock(), fact_id))
        self.db.execute("INSERT INTO facts_fts (rowid, text) VALUES (?,?)", (fact_id, text))
        self.db.commit()

    async def upsert_fact(self, kind: FactKind, text: str, about: int | None, source: str) -> tuple[int, bool]:
        emb = (await self.embedder.embed([text]))[0]
        rows = self.db.execute("SELECT id, text, emb FROM facts WHERE kind=?", (kind,)).fetchall()
        best = max(rows, key=lambda r: float(_vec(r[2]) @ emb), default=None)
        if best is not None and float(_vec(best[2]) @ emb) >= DEDUPE_COS:
            self._set_fact_text(best[0], best[1], text, emb)
            return best[0], False
        return self._insert_fact(kind, text, about, source, emb), True

    async def update_fact(self, fact_id: int, text: str) -> bool:
        r = self.db.execute("SELECT text FROM facts WHERE id=?", (fact_id,)).fetchone()
        if r is None:
            return False
        self._set_fact_text(fact_id, r[0], text, (await self.embedder.embed([text]))[0])
        return True

    def delete_fact(self, fact_id: int) -> bool:
        r = self.db.execute("SELECT text FROM facts WHERE id=?", (fact_id,)).fetchone()
        if r is None:
            return False
        self.db.execute("INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', ?, ?)", (fact_id, r[0]))
        self.db.execute("DELETE FROM facts WHERE id=?", (fact_id,))
        self.db.commit()
        return True

    def _facts(self, where: str, args: tuple) -> list[Fact]:
        rows = self.db.execute(
            f"SELECT id, kind, text, about, source, created, updated FROM facts {where} ORDER BY id", args)
        return [Fact(*r) for r in rows]

    def facts_about(self, user_id: int | None) -> list[Fact]:
        if user_id is None:
            return self._facts("WHERE about IS NULL", ())
        return self._facts("WHERE about=?", (user_id,))

    def all_facts(self) -> list[Fact]:
        return self._facts("", ())

    async def search_facts(self, query: str, k: int = 5) -> list[Fact]:
        hits = await self._hybrid("facts", query, k, "WHERE kind='fact'")
        by_id = {f.id: f for f in self._facts("WHERE kind='fact'", ())}
        return [by_id[i] for i, _ in hits if i in by_id]

    def slang_in(self, texts: list[str]) -> list[Fact]:
        tokens = {w for t in texts for w in re.findall(r"\w+", t.lower())}
        return [f for f in self._facts("WHERE kind='slang'", ())
                if f.text.split("=", 1)[0].strip().lower() in tokens]

    def all_slang(self, limit: int = 80) -> list[str]:
        """Every slang meaning, one per word. Words sharing a 4-letter stem (saiba/saibos) count as one;
        a member-taught entry beats an automatic one, otherwise the newest wins."""
        from .trigger import fold
        best: dict[str, Fact] = {}
        for f in self._facts("WHERE kind='slang'", ()):
            word = fold(f.text.split("=", 1)[0].strip()).split()
            key = word[0][:4] if word else ""
            cur = best.get(key)
            rank = (f.source.startswith("cmd:"), f.updated, f.id)
            if cur is None or rank > (cur.source.startswith("cmd:"), cur.updated, cur.id):
                best[key] = f
        return [f.text for f in sorted(best.values(), key=lambda f: f.id)][:limit]

    # ---- profiles -------------------------------------------------------
    def set_profile(self, user_id: int, text: str) -> None:
        self.db.execute("INSERT INTO profiles (user_id, text, updated) VALUES (?,?,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET text=excluded.text, updated=excluded.updated",
                        (user_id, text, self.clock()))
        self.db.commit()

    def profiles(self) -> dict[int, str]:
        return {r[0]: r[1] for r in self.db.execute("SELECT user_id, text FROM profiles")}

    async def search_chunks(self, query: str, k: int = 3, chat_id: int | None = None) -> list[ChunkHit]:
        out = []
        where, args = ("WHERE chat_id=?", (chat_id,)) if chat_id is not None else ("", ())
        for cid, score in await self._hybrid("chunks", query, k, where, args):
            r = self.db.execute("SELECT chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text "
                                "FROM chunks WHERE id=?", (cid,)).fetchone()
            out.append(ChunkHit(Chunk(*r), score))
        return out
