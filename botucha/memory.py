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
RRF_K = 60  # reciprocal rank fusion constant: the usual value, rank 1 is worth little more than rank 5
EMBED_BATCH = 32  # chunks per embedding request: a few seconds on CPU, far from the client timeout
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
class Person:
    id: int
    name: str
    aliases: list[str]
    user_id: int | None


@dataclass
class Relation:
    """A directed, explicit link: a is <rel> of b (Jonas – darbdavys → Petras)."""
    id: int
    a: Person
    rel: str
    b: Person

    def __str__(self) -> str:
        return f"{self.a.name} – {self.rel} → {self.b.name}"


@dataclass
class ChunkHit:
    chunk: Chunk
    score: float
    fts: bool = False


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
    async def index_new_chunks(self, chat_id: int, *, force: bool = False, limit: int | None = None) -> int:
        """Embed and store the chunks closed since the last call, at most limit of them.
        They go to the embedder EMBED_BATCH at a time and each batch is saved with its cursor, so a
        failure halfway keeps what was done and the next call goes on from there."""
        async with self._index_lock:  # reply worker, learning and bootstrap may call this concurrently
            return await self._index_new_chunks(chat_id, force, limit)

    async def _index_new_chunks(self, chat_id: int, force: bool, limit: int | None) -> int:
        key = f"chunk_cursor:{chat_id}"
        cursor = int(self.store.get_state(key, "0"))
        rows = self.store.messages_after(chat_id, cursor)
        if not rows:
            return 0
        rowid_of = {m.msg_id: rid for rid, m in rows}
        chunks = build_chunks([m for _, m in rows], gap_s=GAP_S)
        if not force and chunks and self.clock() - chunks[-1].end_ts <= GAP_S:
            chunks = chunks[:-1]  # still open: more messages may join it
        if limit is not None:
            chunks = chunks[:limit]
        for i in range(0, len(chunks), EMBED_BATCH):
            part = chunks[i:i + EMBED_BATCH]
            embs = await self.embedder.embed([c.text for c in part])
            for c, e in zip(part, embs):
                cur = self.db.execute(
                    "INSERT INTO chunks (chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text, emb) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (c.chat_id, c.first_msg_id, c.last_msg_id, c.start_ts, c.end_ts, c.text, _blob(e)))
                self.db.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?,?)", (cur.lastrowid, c.text))
            # same transaction as the chunks: a crash can never leave them stored but not counted
            self.db.execute("INSERT INTO state (key, value) VALUES (?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, str(rowid_of[part[-1].last_msg_id])))
            self.db.commit()
        return len(chunks)

    def chunks_after(self, chat_id: int, chunk_id: int) -> list[tuple[int, Chunk]]:
        rows = self.db.execute(
            "SELECT id, chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text FROM chunks "
            "WHERE chat_id=? AND id>? ORDER BY id", (chat_id, chunk_id)).fetchall()
        return [(r[0], Chunk(*r[1:])) for r in rows]

    async def _hybrid(self, table: str, query: str, k: int, where: str = "",
                      args: tuple = ()) -> list[tuple[int, float, bool]]:
        """Meaning and words together: the cosine ranking and the FTS (word match) ranking are merged by
        reciprocal rank fusion, so a chunk holding the one rare word asked about can win over chunks that are
        merely about the same kind of thing. Returns (id, cosine, matched by FTS), best first."""
        q = (await self.embedder.embed([query]))[0]
        rows = self.db.execute(f"SELECT id, emb FROM {table} {where}", args).fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        scores = np.stack([_vec(r[1]) for r in rows]) @ q
        by_cosine = [ids[i] for i in np.argsort(-scores)]
        allowed = set(ids)
        by_words: list[int] = []
        fq = fts_query(query)
        if fq:
            try:  # bm25 order; rows outside the filter (another chat, the visible transcript) do not count
                hits = self.db.execute(f"SELECT rowid FROM {table}_fts WHERE {table}_fts MATCH ? ORDER BY rank "
                                       f"LIMIT ?", (fq, 10 + 4 * k + len(ids) // 50))
                by_words = [r[0] for r in hits if r[0] in allowed][:10]
            except Exception:
                pass
        fused: dict[int, float] = {}
        for ranking in (by_cosine, by_words):
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank + 1)
        score_of = dict(zip(ids, scores.tolist()))
        words = set(by_words)
        best = sorted(fused, key=lambda i: (-fused[i], -score_of[i]))[:k]
        return [(i, score_of[i], i in words) for i in best]

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
        if kind == "fact":
            self._link(cur.lastrowid, text, about)
        self.db.commit()
        return cur.lastrowid

    def _set_fact_text(self, fact_id: int, old: str, text: str, emb, about: int | None = None) -> None:
        """New text for a fact. about, when given, also moves who the fact is about."""
        self.db.execute("INSERT INTO facts_fts (facts_fts, rowid, text) VALUES ('delete', ?, ?)", (fact_id, old))
        self.db.execute("UPDATE facts SET text=?, emb=?, updated=?, about=COALESCE(?, about) WHERE id=?",
                        (text, _blob(emb), self.clock(), about, fact_id))
        self.db.execute("INSERT INTO facts_fts (rowid, text) VALUES (?,?)", (fact_id, text))
        r = self.db.execute("SELECT kind, about FROM facts WHERE id=?", (fact_id,)).fetchone()
        if r and r[0] == "fact":
            self._link(fact_id, text, r[1])
        self.db.commit()

    async def upsert_fact(self, kind: FactKind, text: str, about: int | None, source: str) -> tuple[int, bool]:
        """(fact id, whether a new fact was added)."""
        fid, outcome = await self.upsert_fact_ex(kind, text, about, source)
        return fid, outcome == "added"

    async def upsert_fact_ex(self, kind: FactKind, text: str, about: int | None,
                             source: str) -> tuple[int, Literal["added", "updated", "kept"]]:
        """Add a fact, or update the near-duplicate it repeats. A fact a person wrote (a chat command or the
        dashboard) is never changed by an automatic one: it is "kept" as it is and nothing is added."""
        emb = (await self.embedder.embed([text]))[0]
        rows = self.db.execute("SELECT id, text, emb, source FROM facts WHERE kind=?", (kind,)).fetchall()
        best = max(rows, key=lambda r: float(_vec(r[2]) @ emb), default=None)
        if best is not None and float(_vec(best[2]) @ emb) >= DEDUPE_COS:
            if source == "auto" and best[3] != "auto":
                return best[0], "kept"
            self._set_fact_text(best[0], best[1], text, emb, about)
            return best[0], "updated"
        return self._insert_fact(kind, text, about, source, emb), "added"

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
        self.db.execute("DELETE FROM fact_people WHERE fact_id=?", (fact_id,))
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
        return [f for f, _, _ in await self.search_facts_scored(query, k)]

    async def search_facts_scored(self, query: str, k: int = 5) -> list[tuple[Fact, float, bool]]:
        hits = await self._hybrid("facts", query, k, "WHERE kind='fact'")
        by_id = {f.id: f for f in self._facts("WHERE kind='fact'", ())}
        return [(by_id[i], score, fts) for i, score, fts in hits if i in by_id]

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

    # ---- people: members and friends outside the group -----------------------
    def _people_rows(self, where: str = "", args: tuple = ()) -> list[Person]:
        rows = self.db.execute(f"SELECT id, name, aliases, user_id FROM people {where} ORDER BY id", args)
        return [Person(r[0], r[1], [a for a in r[2].split(",") if a], r[3]) for r in rows]

    def people(self) -> list[Person]:
        return self._people_rows()

    def add_person(self, name: str, aliases: list[str], user_id: int | None = None) -> int:
        """Add a person (or merge aliases into an existing one) and relink all facts."""
        clean = [a.strip().lower() for a in aliases if a.strip()]
        cur = self._people_rows("WHERE name=?", (name,))
        if cur:
            merged = list(dict.fromkeys(cur[0].aliases + clean))
            self.db.execute("UPDATE people SET aliases=?, user_id=COALESCE(?, user_id) WHERE id=?",
                            (",".join(merged), user_id, cur[0].id))
            pid = cur[0].id
        else:
            pid = self.db.execute("INSERT INTO people (name, aliases, user_id) VALUES (?,?,?)",
                                  (name, ",".join(dict.fromkeys(clean)), user_id)).lastrowid
        self.relink_all()
        return pid

    def ensure_member_person(self, user_id: int, name: str, username: str | None) -> None:
        if not self._people_rows("WHERE user_id=?", (user_id,)):
            self.add_person(name, [username] if username else [], user_id)

    @staticmethod
    def _terms(p: Person) -> list[list[str]]:
        from .trigger import fold
        return [re.findall(r"\w+", fold(t)) for t in [p.name, *p.aliases] if t]

    def people_in(self, text: str) -> list[Person]:
        """People whose name or listed word form appears as whole words, in order of appearance."""
        from .trigger import fold
        words = re.findall(r"\w+", fold(text))
        found: list[tuple[int, Person]] = []
        for p in self.people():
            pos = [i for term in self._terms(p) for i in range(len(words) - len(term) + 1)
                   if term and words[i:i + len(term)] == term]
            if pos:
                found.append((min(pos), p))
        return [p for _, p in sorted(found, key=lambda x: (x[0], x[1].id))]

    def find_person(self, alias: str) -> Person | None:
        hits = self.people_in(alias.lstrip("@"))
        return hits[0] if hits else None

    def _link(self, fact_id: int, text: str, about: int | None) -> None:
        self.db.execute("DELETE FROM fact_people WHERE fact_id=?", (fact_id,))
        ids = {p.id for p in self.people_in(text)}
        if about is not None:
            ids |= {p.id for p in self._people_rows("WHERE user_id=?", (about,))}
        self.db.executemany("INSERT INTO fact_people (fact_id, person_id) VALUES (?,?)", [(fact_id, i) for i in ids])

    def relink_all(self) -> None:
        for fid, text, about in self.db.execute("SELECT id, text, about FROM facts WHERE kind='fact'").fetchall():
            self._link(fid, text, about)
        self.db.commit()

    def get_person(self, person_id: int) -> Person | None:
        rows = self._people_rows("WHERE id=?", (person_id,))
        return rows[0] if rows else None

    def set_aliases(self, person_id: int, aliases: list[str]) -> bool:
        """Replace a person's word forms and relink every fact."""
        if self.get_person(person_id) is None:
            return False
        clean = list(dict.fromkeys(a.strip().lower() for a in aliases if a.strip()))
        self.db.execute("UPDATE people SET aliases=? WHERE id=?", (",".join(clean), person_id))
        self.relink_all()
        return True

    def comentions(self) -> list[tuple[int, int, int]]:
        """(a, b, shared facts) for every pair of people mentioned in the same fact, a < b."""
        return [tuple(r) for r in self.db.execute(
            "SELECT a.person_id, b.person_id, COUNT(*) FROM fact_people a JOIN fact_people b "
            "ON a.fact_id=b.fact_id AND a.person_id < b.person_id GROUP BY a.person_id, b.person_id "
            "ORDER BY a.person_id, b.person_id")]

    def people_of_fact(self, fact_id: int) -> list[Person]:
        return self._people_rows("WHERE id IN (SELECT person_id FROM fact_people WHERE fact_id=?)", (fact_id,))

    def person_facts(self, person_id: int) -> list[Fact]:
        return self._facts("WHERE id IN (SELECT fact_id FROM fact_people WHERE person_id=?)", (person_id,))

    def related(self, person_id: int) -> list[Person]:
        """Other people sharing facts with this one, most shared first."""
        rows = self.db.execute(
            "SELECT b.person_id, COUNT(*) n FROM fact_people a JOIN fact_people b ON a.fact_id=b.fact_id "
            "WHERE a.person_id=? AND b.person_id!=? GROUP BY b.person_id ORDER BY n DESC, b.person_id",
            (person_id, person_id)).fetchall()
        by_id = {p.id: p for p in self.people()}
        return [by_id[r[0]] for r in rows if r[0] in by_id]

    # ---- explicit relations between people --------------------------------
    def add_relation(self, a: str, rel: str, b: str, source: str) -> int | None:
        """Link two known people (any name or word form); None if either is unknown. Duplicates return the old id."""
        pa, pb, rel = self.find_person(a), self.find_person(b), rel.strip().lower()
        if pa is None or pb is None or pa.id == pb.id or not rel:
            return None
        self.db.execute("INSERT OR IGNORE INTO relations (a, rel, b, source, created) VALUES (?,?,?,?,?)",
                        (pa.id, rel, pb.id, source, self.clock()))
        self.db.commit()
        return self.db.execute("SELECT id FROM relations WHERE a=? AND rel=? AND b=?", (pa.id, rel, pb.id)).fetchone()[0]

    def relations(self, person_id: int | None = None) -> list[Relation]:
        where, args = ("WHERE a=? OR b=?", (person_id, person_id)) if person_id is not None else ("", ())
        by_id = {p.id: p for p in self.people()}
        rows = self.db.execute(f"SELECT id, a, rel, b FROM relations {where} ORDER BY id", args).fetchall()
        return [Relation(i, by_id[a], rel, by_id[b]) for i, a, rel, b in rows if a in by_id and b in by_id]

    def delete_relation(self, relation_id: int) -> bool:
        n = self.db.execute("DELETE FROM relations WHERE id=?", (relation_id,)).rowcount
        self.db.commit()
        return n > 0

    def people_lines(self, max_facts: int = 6, only: set[int] | None = None) -> list[str]:
        """One line per person with facts or relations:
        'Name (aliases): fact; fact. Ryšiai: A – rel → B. Susiję: C' (Susiję = only co-mentioned in facts).
        only = person ids to include (None = everyone)."""
        lines = []
        for p in self.people():
            if only is not None and p.id not in only:
                continue
            facts = [f.text.rstrip(".") for f in self.person_facts(p.id)][-max_facts:]  # the newest ones
            rels = self.relations(p.id)
            linked = {r.a.id for r in rels} | {r.b.id for r in rels}
            rel = [r.name for r in self.related(p.id) if r.id not in linked]
            if not facts and not rels:
                continue
            head = p.name + (f" ({', '.join(p.aliases[:3])})" if p.aliases else "")
            body = f"{'; '.join(facts)}." if facts else ""
            if rels:
                body += f" Ryšiai: {'; '.join(map(str, rels))}."
            if rel:
                body += f" Susiję: {', '.join(rel)}"
            lines.append(f"{head}: {body.strip()}")
        return lines

    # ---- profiles -------------------------------------------------------
    def set_profile(self, user_id: int, text: str) -> None:
        self.db.execute("INSERT INTO profiles (user_id, text, updated) VALUES (?,?,?) "
                        "ON CONFLICT(user_id) DO UPDATE SET text=excluded.text, updated=excluded.updated",
                        (user_id, text, self.clock()))
        self.db.commit()

    def profiles(self) -> dict[int, str]:
        return {r[0]: r[1] for r in self.db.execute("SELECT user_id, text FROM profiles")}

    async def search_chunks(self, query: str, k: int = 3, chat_id: int | None = None,
                            before_msg_id: int | None = None) -> list[ChunkHit]:
        """before_msg_id: only chunks that end before this message (the oldest one still in view), so a reply
        is not handed back what its own transcript already shows."""
        out = []
        cond, args = [], []
        if chat_id is not None:
            cond.append("chat_id=?")
            args.append(chat_id)
        if before_msg_id is not None:
            cond.append("last_msg_id<?")
            args.append(before_msg_id)
        where, args = ("WHERE " + " AND ".join(cond) if cond else ""), tuple(args)
        for cid, score, fts in await self._hybrid("chunks", query, k, where, args):
            r = self.db.execute("SELECT chat_id, first_msg_id, last_msg_id, start_ts, end_ts, text "
                                "FROM chunks WHERE id=?", (cid,)).fetchone()
            out.append(ChunkHit(Chunk(*r), score, fts))
        return out
