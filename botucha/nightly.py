"""The overnight recheck: his real replies, judged again, and turned into training data.

  uv run python -m botucha.nightly --config config.toml --judge OLLAMA_MODEL [--limit 40] [--n 3] [--min-score 4]
      [--hours 6.5] [--unanswered] [--batch 25]
  uv run python -m botucha.nightly --backfill-pairs   (pairs from the examples already collected)

For each moment where he answered in the group (newest first, each moment once):
  1. the chat is replayed as it was just before his reply: later messages, chunks and facts are left out
     (profiles cannot be rewound, so they are today's);
  2. the current model makes n new replies there, with the same prompt the bot would build;
  3. a judge (another local model) scores them and his real reply against persona.md, after all replies are
     made, so Ollama swaps models once;
  4. the example is the group's /pataisyk correction when there is one, otherwise the best clean reply that
     scores at least min_score (a reply the group rated 👎 never wins; one rated 👍 wins a tie).

With --unanswered, members' group messages he never answered come after his replies: the chat is replayed the
same way and the best new reply is the example (there is no real reply to compare).

It writes training/examples-DATE.jsonl (chat-format messages: system, user, assistant, plus every candidate
and its score), training/pairs-DATE.jsonl (preference pairs for DPO/ORPO: the example against the worst reply
the judge saw there), training/report-DATE.md, and training/done.txt (moments already judged). With --hours it
works in batches and writes after each one, so a night cut short keeps what it finished. All of it holds real
messages and stays on this machine (training/ is git-ignored). The live database is only read: it is copied
into memory through a read-only connection. A moment whose replies or verdicts all failed is tried again the
next night. While it runs it uses the bot's model and then the judge's, so schedule it when the group sleeps.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from .app import CANNED, Botucha, ReplyJob, is_private
from .brain import strip_address
from .config import load_config
from .embed import OllamaEmbedder
from .evaluation import check_reply
from .forwards import PREFIX as FORWARD
from .llm import OllamaLLM
from .memory import Memory
from .persona_checks import Verdict, judge
from .store import Store

log = logging.getLogger(__name__)

TRANSCRIPT_LINES = 8  # what the judge sees of the chat before the reply
SERIOUS_RUBRIC = "Tai /rimtai klausimas: atsakymas turi būti rimtas, aiškus ir teisingas, be žargono."
DONE_FILE = "done.txt"
MIN_WORDS, MIN_CHARS = 3, 15  # an unanswered message shorter than this is no moment
PAIR_GAP = 2  # judge points between the chosen and the rejected reply of a preference pair


@dataclass
class Moment:
    trace_id: int
    chat_id: int
    msg_id: int  # the message he answered
    ts: float  # when it was written
    reply: str  # what he sent, one message per line
    direct: bool
    serious: bool
    recall: bool
    up: int = 0
    down: int = 0
    corrections: list[str] = field(default_factory=list)  # oldest first
    unanswered: bool = False  # a member's message he never answered: what would he have said there?
    boss_up: bool = False  # the admin marked his reply /gerai (👍): it is the example whatever the judge says

    @property
    def key(self) -> str:
        """What done.txt remembers: the trace id of his reply, or m<chat>:<msg> for an unanswered message."""
        return f"m{self.chat_id}:{self.msg_id}" if self.unanswered else str(self.trace_id)


@dataclass
class Candidate:
    texts: list[str]
    prompt: list[dict]  # the system and user messages the model got
    origin: str  # "generated" or "original"
    problems: list[str] = field(default_factory=list)


@dataclass
class Scored:
    candidate: Candidate
    verdict: Verdict
    problems: list[str]


@dataclass
class Example:
    source: str  # "correction", "approved" (his real reply, 👍 from the admin), "original" or "generated"
    text: str
    score: int | None
    prompt: list[dict]


# ---- reading the live database ---------------------------------------------------------------------------
def open_readonly(path: Path) -> Store:
    """The whole database copied into memory. The file is opened read-only, so nothing here can change it."""
    mem = Store(":memory:")
    try:
        src = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
        src.execute("SELECT 1 FROM sqlite_master").fetchone()
    except sqlite3.OperationalError:  # WAL without its -shm file (the bot is stopped): a plain read is safe too
        src = sqlite3.connect(str(path))
    try:
        src.backup(mem.conn)
    finally:
        src.close()
    return mem


def _copy(store: Store) -> Store:
    mem = Store(":memory:")
    store.conn.backup(mem.conn)
    return mem


def moments(store: Store, done: set, limit: int | None, admin_id: int | None = None) -> list[Moment]:
    """His replies in groups (sent or sent from a fallback), newest first, skipping the done ones."""
    rows = store.conn.execute(
        "SELECT t.id, t.chat_id, t.msg_id, t.trigger, t.reply, t.started, m.ts FROM traces t "
        "JOIN messages m ON m.chat_id = t.chat_id AND m.msg_id = t.msg_id "
        "WHERE t.kind = 'reply' AND t.outcome IN ('sent', 'fallback') AND t.reply IS NOT NULL "
        "ORDER BY t.started DESC, t.id DESC").fetchall()
    out = []
    for tid, chat_id, msg_id, trigger, reply, _started, ts in rows:
        if str(tid) in done or tid in done or is_private(chat_id):
            continue
        sent = [r[0] for r in store.conn.execute(
            "SELECT msg_id FROM trace_messages WHERE trace_id = ?", (tid,))]
        marks = ",".join("?" * len(sent))
        up = down = 0
        boss_up = False
        corrections: list[str] = []
        if sent:
            boss_up = admin_id is not None and store.conn.execute(
                f"SELECT 1 FROM feedback WHERE chat_id = ? AND user_id = ? AND score > 0 AND msg_id IN ({marks})",
                (chat_id, admin_id, *sent)).fetchone() is not None
            up, down = store.conn.execute(
                f"SELECT COALESCE(SUM(score > 0), 0), COALESCE(SUM(score < 0), 0) FROM feedback "
                f"WHERE chat_id = ? AND msg_id IN ({marks})", (chat_id, *sent)).fetchone()
            corrections = [r[0] for r in store.conn.execute(
                f"SELECT text FROM corrections WHERE chat_id = ? AND msg_id IN ({marks}) ORDER BY ts",
                (chat_id, *sent))]
        kinds = set(trigger.split("+")) if trigger else set()
        uninvited = bool(kinds) and all(k.startswith(("random", "keyword")) for k in kinds)
        out.append(Moment(tid, chat_id, msg_id, ts, reply, direct=not uninvited, serious="serious" in kinds,
                          recall="recall" in kinds, up=int(up), down=int(down), corrections=corrections, boss_up=boss_up))
        if limit is not None and len(out) >= limit:
            break
    return out


def unanswered(store: Store, done: set, limit: int | None) -> list[Moment]:
    """Members' group messages he did not answer, newest first. Commands, forwards and one- or two-word lines
    are left out: there is little to answer there."""
    if limit is not None and limit <= 0:
        return []
    answered = set(store.conn.execute("SELECT chat_id, msg_id FROM traces WHERE kind = 'reply'").fetchall())
    rows = store.conn.execute("SELECT chat_id, msg_id, ts, text FROM messages WHERE is_bot = 0 "
                              "ORDER BY ts DESC, rowid DESC").fetchall()
    out = []
    for chat_id, msg_id, ts, text in rows:
        m = Moment(0, chat_id, msg_id, ts, "", direct=True, serious=False, recall=False, unanswered=True)
        t = text.strip()
        if (is_private(chat_id) or m.key in done or (chat_id, msg_id) in answered or t.startswith(("/", FORWARD))
                or len(t) < MIN_CHARS or len(t.split()) < MIN_WORDS):
            continue
        out.append(m)
        if limit is not None and len(out) >= limit:
            break
    return out


def as_of(store: Store, m: Moment) -> Store:
    """A copy of the chat as it was just before his reply. The source store is not changed."""
    then = _copy(store)
    c = then.conn
    c.execute("DELETE FROM messages WHERE chat_id = ? AND msg_id > ?", (m.chat_id, m.msg_id))
    c.execute("DELETE FROM chunks WHERE chat_id = ? AND last_msg_id >= ?", (m.chat_id, m.msg_id))
    c.execute("DELETE FROM facts WHERE created > ?", (m.ts,))
    c.execute("DELETE FROM fact_people WHERE fact_id NOT IN (SELECT id FROM facts)")
    c.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild')")
    c.execute("INSERT INTO facts_fts(facts_fts) VALUES ('rebuild')")
    c.commit()
    return then


def transcript(store: Store, m: Moment, lines: int = TRANSCRIPT_LINES) -> str:
    rows = store.conn.execute(
        "SELECT name, text FROM messages WHERE chat_id = ? AND msg_id <= ? ORDER BY rowid DESC LIMIT ?",
        (m.chat_id, m.msg_id, lines)).fetchall()
    return "\n".join(f"{name}: {text}" for name, text in reversed(rows))


# ---- making new replies ----------------------------------------------------------------------------------
class _Recorder:
    """Passes calls through and keeps the last real prompt (a cache warm-up asks for one token)."""

    def __init__(self, llm):
        self.llm, self.last = llm, None

    def __getattr__(self, name):
        return getattr(self.llm, name)

    async def chat(self, messages, *, num_predict, fmt_json=False):
        if num_predict > 1:
            self.last = messages
        return await self.llm.chat(messages, num_predict=num_predict, fmt_json=fmt_json)

    async def chat_ex(self, messages, *, num_predict, fmt_json=False, images=None):
        if num_predict > 1:
            self.last = messages
        return await self.llm.chat_ex(messages, num_predict=num_predict, fmt_json=fmt_json, images=images)


class _Capture:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, chat_id, texts, reply_to):
        self.sent += texts
        return [10**9 + len(self.sent)]

    async def react(self, chat_id, msg_id, emoji):
        pass

    async def typing(self, chat_id):
        pass

    async def leave(self, chat_id):
        pass

    async def fetch_image(self, file_id):  # no Telegram here: an image moment is answered from its text
        raise RuntimeError("no images in the overnight recheck")


async def _nosleep(_):
    return None


def _bot(cfg, store: Store, embedder, llm, seed: int, prepare: Callable[[Botucha], None] | None) -> tuple:
    out = _Capture()
    bot = Botucha(cfg, store, Memory(store, embedder), llm, out, rng=random.Random(seed), bot_user_id=0,
                  bot_username="botucha_bot", sleep=_nosleep, started_at=0)
    if prepare:
        prepare(bot)
    return bot, out


def member_names(cfg, store: Store, embedder) -> list[str]:
    bot, _ = _bot(cfg, _copy(store), embedder, None, 0, None)
    return bot._member_names()


async def generate(cfg, then: Store, embedder, llm, m: Moment, n: int,
                   prepare: Callable[[Botucha], None] | None = None) -> list[Candidate]:
    """n new replies at that moment, each on its own copy. A failed or canned reply is no candidate."""
    out: list[Candidate] = []
    for i in range(n):
        rec = _Recorder(llm)
        bot, box = _bot(cfg, _copy(then), embedder, rec, i, prepare)
        await bot.run_job([ReplyJob(m.chat_id, m.msg_id, direct=m.direct, serious=m.serious, recall=m.recall)])
        texts = [t for t in box.sent if t != CANNED]
        if texts and rec.last is not None:
            out.append(Candidate(texts, [dict(x) for x in rec.last], "generated",
                                 check_reply(texts, bot._member_names(), serious=m.serious)))
    return out


# ---- choosing ----------------------------------------------------------------------------------------------
def _clean(s: Scored, min_score: int) -> bool:
    v = s.verdict
    return v.error is None and v.score is not None and v.score >= min_score and not v.ooc and not s.problems


def choose(m: Moment, scored: list[Scored], min_score: int) -> Example | None:
    if not scored:
        return None
    if m.corrections:  # the group said what he should have written
        return Example("correction", m.corrections[-1], None, scored[0].candidate.prompt)
    approved = next((s for s in scored if s.candidate.origin == "original"), None) if m.boss_up else None
    if approved:  # the admin said this real reply was good: the judge does not overrule him
        return Example("approved", "\n".join(approved.candidate.texts), approved.verdict.score, approved.candidate.prompt)
    liked, disliked = m.up > m.down, m.down > m.up
    pool = [s for s in scored if _clean(s, min_score) and not (disliked and s.candidate.origin == "original")]
    if not pool:
        return None
    best = max(pool, key=lambda s: (s.verdict.score, liked and s.candidate.origin == "original"))
    return Example(best.candidate.origin, "\n".join(best.candidate.texts), best.verdict.score, best.candidate.prompt)


# ---- the night -----------------------------------------------------------------------------------------------
def _done(out_dir: Path) -> set[str]:
    p = out_dir / DONE_FILE
    return set(p.read_text().split()) if p.exists() else set()


def _record(m: Moment, ex: Example, scored: list[Scored], day: str) -> dict:
    return {"date": day, "key": m.key, "kind": "unanswered" if m.unanswered else "reply",
            "trace_id": None if m.unanswered else m.trace_id, "chat_id": m.chat_id, "msg_id": m.msg_id,
            "source": ex.source, "score": ex.score, "messages": ex.prompt + [{"role": "assistant", "content": ex.text}],
            "human": {"up": m.up, "down": m.down, "corrections": m.corrections, "boss_up": m.boss_up},
            "candidates": [{"origin": s.candidate.origin, "text": "\n".join(s.candidate.texts),
                            "score": s.verdict.score, "error": s.verdict.error, "problems": s.problems,
                            "ooc": [{"text": a.text, "why": a.why} for a in s.verdict.ooc],
                            "feedback": s.verdict.feedback} for s in scored]}


def pair_from_record(rec: dict) -> dict | None:
    """A preference pair (DPO/ORPO) from one training example: its answer against the worst reply the judge saw
    there. A correction is preferred over his real reply; otherwise the gap must be PAIR_GAP judge points, or
    one point when the worse reply also broke character or a rule check. A reply the admin approved is preferred
    over the worst other reply with no gap needed."""
    chosen = rec["messages"][-1]["content"]
    others = [c for c in rec["candidates"] if c["text"] != chosen]
    if rec["source"] == "correction":
        rejected = next((c for c in others if c["origin"] == "original"), None)
    else:
        scored = [c for c in others if c["score"] is not None]
        rejected = min(scored, key=lambda c: (c["score"], -len(c["problems"]) - len(c["ooc"])), default=None)
        if rejected is not None and rec["source"] != "approved":
            gap = (rec["score"] or 0) - rejected["score"]
            if gap < PAIR_GAP and not (gap >= 1 and (rejected["problems"] or rejected["ooc"])):
                rejected = None
    if rejected is None:
        return None
    return {"date": rec["date"], "key": rec.get("key", str(rec.get("trace_id"))), "source": rec["source"],
            "prompt": rec["messages"][:-1], "chosen": chosen, "rejected": rejected["text"],
            "chosen_score": rec["score"], "rejected_score": rejected["score"],
            "rejected_why": [*rejected["problems"], *(a["why"] for a in rejected["ooc"])]}


def _append(path: Path, rows: list[dict]) -> None:
    if rows:
        with path.open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def backfill_pairs(out_dir: Path) -> list[Path]:
    """Pairs from the examples written before pairs existed (a day that has a pairs file is left alone)."""
    written = []
    for ex in sorted(out_dir.glob("examples-*.jsonl")):
        day = ex.stem.removeprefix("examples-")
        target = out_dir / f"pairs-{day}.jsonl"
        if target.exists():
            continue
        recs = [json.loads(x) for x in ex.read_text(encoding="utf-8").splitlines() if x.strip()]
        _append(target, [p for r in recs if (p := pair_from_record(r))])
        if target.exists():
            written.append(target)
    return written


def _mean(xs: list[float]) -> str:
    return f"{sum(xs) / len(xs):.2f}" if xs else "–"


def _report(day: str, judged: list[tuple[Moment, str, list[Scored], Example | None]], skipped: int,
            min_score: int, pairs: int = 0) -> str:
    real = [s.verdict.score for _, _, ss, _ in judged for s in ss
            if s.candidate.origin == "original" and s.verdict.score is not None]
    best = [max(s.verdict.score for s in ss if s.verdict.score is not None) for _, _, ss, _ in judged
            if any(s.verdict.score is not None for s in ss)]
    made = [ex for *_, ex in judged if ex]
    by = {k: sum(1 for e in made if e.source == k) for k in ("correction", "approved", "original", "generated")}
    new = sum(1 for m, *_ in judged if m.unanswered)
    lines = [f"# Overnight recheck ({day})", "",
             f"- moments judged: {len(judged)} (his replies {len(judged) - new}, unanswered messages {new})"
             + (f", tried again next night: {skipped}" if skipped else ""),
             f"- training examples written: {len(made)}/{len(judged)} (score ≥ {min_score}, no out-of-character "
             f"line): correction {by['correction']}, approved by the admin {by['approved']}, his real reply "
             f"{by['original']}, new reply {by['generated']}",
             f"- preference pairs written: {pairs}",
             f"- his real reply, mean judge score: {_mean(real)}; best reply per moment: {_mean(best)}", ""]
    weak = [(m, t, s) for m, t, ss, _ in judged for s in ss
            if s.candidate.origin == "original" and s.verdict.score is not None and s.verdict.score <= 2]
    if weak:
        lines += ["## His weakest real replies", ""]
        for m, t, s in weak:
            lines += [f"### trace {m.trace_id}: {s.verdict.score}/5", *[f"    {x}" for x in t.splitlines()],
                      "", *[f"    → {x}" for x in s.candidate.texts], "", f"judge: {s.verdict.feedback}",
                      *[f"- ✗ „{a.text}“ — {a.why}" for a in s.verdict.ooc], ""]
    return "\n".join(lines) + "\n"


async def run_night(cfg, db_path: Path, embedder, llm, judge_llm, out_dir: Path, *, limit: int | None, n: int,
                    min_score: int, today: str | None = None,
                    prepare: Callable[[Botucha], None] | None = None, include_unanswered: bool = False,
                    deadline: float | None = None, batch: int = 25,
                    clock: Callable[[], float] = time.time) -> tuple[Path, Path]:
    """His replies first, then (include_unanswered) members' messages he never answered, in batches: each batch
    makes every reply, then judges them (one model swap each way) and writes its examples, pairs and done.txt,
    so a night cut short keeps what it finished. Past the deadline no new moment is started."""
    day = today or str(date.today())
    out_dir.mkdir(parents=True, exist_ok=True)
    live = open_readonly(db_path)
    names = member_names(cfg, live, embedder)
    done = _done(out_dir)
    todo = moments(live, done, limit, cfg.telegram.admin_id)
    if include_unanswered:
        todo += unanswered(live, done, None if limit is None else limit - len(todo))
    data, pairs_path = out_dir / f"examples-{day}.jsonl", out_dir / f"pairs-{day}.jsonl"
    report = out_dir / f"report-{day}.md"
    judged_all: list[tuple[Moment, str, list[Scored], Example | None]] = []
    skipped = pairs_n = 0
    late = lambda: deadline is not None and clock() >= deadline  # noqa: E731
    for start in range(0, len(todo), max(1, batch)):
        if late():
            break
        made: list[tuple[Moment, str, list[Candidate]]] = []
        tried = 0
        for m in todo[start:start + batch]:  # every reply of the batch first, then every verdict
            if late():
                break
            tried += 1
            if m.direct:  # a direct reply is a Telegram reply: the name in front is not part of the answer
                m.corrections = ["\n".join(strip_address(c.split("\n"), names)) for c in m.corrections]
            then = as_of(live, m)
            t = time.time()
            cands = await generate(cfg, then, embedder, llm, m, n, prepare)
            log.info("%s: %d/%d replies in %.0fs", m.key, len(cands), n, time.time() - t)
            if cands:
                if not m.unanswered:
                    original = m.reply.split("\n")
                    if m.direct:
                        original = strip_address(original, names) or original
                    cands.append(Candidate(original, cands[0].prompt, "original",
                                           check_reply(original, names, serious=m.serious)))
                made.append((m, transcript(then, m), cands))
        persona = cfg.paths.persona.read_text(encoding="utf-8")
        judged = []
        skipped += tried - len(made)
        for m, text, cands in made:
            scored = []
            for c in cands:
                v = await judge(judge_llm, persona, text, c.texts, SERIOUS_RUBRIC if m.serious else "",
                                members=names)
                scored.append(Scored(c, v, c.problems))
            if all(s.verdict.error for s in scored):
                skipped += 1
                continue
            judged.append((m, text, scored, choose(m, scored, min_score)))
        rows = [_record(m, ex, ss, day) for m, _, ss, ex in judged if ex]
        prs = [p for r in rows if (p := pair_from_record(r))]
        _append(data, rows)
        _append(pairs_path, prs)
        with (out_dir / DONE_FILE).open("a") as f:
            f.writelines(f"{m.key}\n" for m, *_ in judged)
        judged_all += judged
        pairs_n += len(prs)
        report.write_text(_report(day, judged_all, skipped, min_score, pairs_n), encoding="utf-8")
        log.info("batch done: %d judged so far, %d examples, %d pairs", len(judged_all),
                 sum(1 for *_, ex in judged_all if ex), pairs_n)
    report.write_text(_report(day, judged_all, skipped, min_score, pairs_n), encoding="utf-8")
    return data, report


def main() -> None:
    from .__main__ import load_env
    from .spell import Speller

    ap = argparse.ArgumentParser(prog="botucha.nightly")
    ap.add_argument("--config", type=Path, default=Path("config.toml"))
    ap.add_argument("--judge", help="local Ollama model that scores the replies against the persona")
    ap.add_argument("--limit", type=int, default=None, help="moments per night (default 40, none with --hours)")
    ap.add_argument("--hours", type=float, default=None, help="start no new moment after this many hours")
    ap.add_argument("--unanswered", action="store_true",
                    help="after his replies, also replay members' messages he never answered")
    ap.add_argument("--batch", type=int, default=25, help="moments made, judged and written together")
    ap.add_argument("--backfill-pairs", action="store_true",
                    help="only write preference pairs from the examples already collected, then stop")
    ap.add_argument("--n", type=int, default=3, help="new replies per moment")
    ap.add_argument("--min-score", type=int, default=4)
    ap.add_argument("--out", type=Path, default=Path("training"))
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.backfill_pairs:
        for p in backfill_pairs(a.out):
            print("wrote", p, sum(1 for _ in p.open()), "pairs", flush=True)
        return
    if not a.judge:
        ap.error("--judge is required")
    limit = a.limit if a.limit is not None or a.hours else 40
    deadline = time.time() + a.hours * 3600 if a.hours else None
    cfg = load_config(a.config.resolve(), {**load_env(a.config.resolve().parent / ".env"), **os.environ})
    llm = OllamaLLM(cfg.model)
    # deterministic, and unloaded a minute after the last verdict so the bot's own model comes back
    judge_llm = OllamaLLM(dataclasses.replace(cfg.model, chat_model=a.judge, temperature=0.0, keep_alive="1m"))
    dicts = Path(__file__).resolve().parent.parent / "data" / "hunspell" / "lt"

    def prepare(bot: Botucha) -> None:
        bot.speller = Speller(dicts, vocab=bot.vocabulary)
    data, report = asyncio.run(run_night(
        cfg, cfg.paths.db, OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model, keep_alive=cfg.model.keep_alive),
        llm, judge_llm, a.out, limit=limit, n=a.n, min_score=a.min_score, prepare=prepare,
        include_unanswered=a.unanswered, deadline=deadline, batch=a.batch))
    print(report.read_text(encoding="utf-8").split("\n## ", 1)[0], flush=True)
    print("wrote", report, "and", data if data.exists() else "no new examples", flush=True)


if __name__ == "__main__":
    main()
