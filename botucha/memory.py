"""Chat memory: conversation chunks, facts, slang and member profiles over SQLite."""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from .chunking import Chunk, build_chunks
from .embed import Embedder
from .store import Store

GAP_S = 1800


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

    # ---- chunks ---------------------------------------------------------
    async def index_new_chunks(self, chat_id: int, *, force: bool = False) -> int:
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

    async def search_chunks(self, query: str, k: int = 3) -> list[ChunkHit]:
        out = []
        for cid, score in await self._hybrid("chunks", query, k):
            r = self.db.execute("SELECT chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text "
                                "FROM chunks WHERE id=?", (cid,)).fetchone()
            out.append(ChunkHit(Chunk(*r), score))
        return out
