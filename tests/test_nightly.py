"""The overnight recheck: real moments where he answered are replayed as they were, a few new replies are made,
a judge scores them all with his real one, and the best becomes a training example. The live DB is only read."""
import hashlib
import json
import sqlite3

import pytest

from botucha.nightly import (Candidate, Moment, Scored, as_of, choose, generate, moments, open_readonly, run_night,
                             transcript)
from botucha.persona_checks import Atom, Verdict
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder, FakeLLM
from tests.test_app import C, make_cfg

BOT = 999


def verdict(score, ooc=0):
    return json.dumps({"atoms": [{"text": "x", "ok": i >= ooc, "why": ""} for i in range(max(ooc, 1))],
                       "score": score, "feedback": "ok"})


def seed(store, chat=C, base=0, trigger="direct", reply="nu jo", outcome="sent", started=None):
    """A member asks, a member adds a line, he answers, the chat goes on; the reply has its trace."""
    m = lambda i, user, name, text, bot=False: store.add_message(  # noqa: E731
        StoredMessage(chat, base + i, user, name, 1000.0 + base + i, text, None, bot))
    m(1, 111, "Tadas", "rytoj perku nvidia")
    m(2, 222, "Ona", "botucha ka manai apie nvidia")
    m(3, BOT, "Botucha", reply, bot=True)
    m(4, 111, "Tadas", "VĖLIAU PARAŠYTA ŽINUTĖ")
    cur = store.conn.execute(
        "INSERT INTO traces (kind, chat_id, msg_id, user_name, trigger, outcome, reply, started) "
        "VALUES ('reply', ?, ?, 'Ona', ?, ?, ?, ?)", (chat, base + 2, trigger, outcome, reply,
                                                       started or 1000.0 + base + 2))
    store.conn.execute("INSERT INTO trace_messages (trace_id, chat_id, msg_id) VALUES (?,?,?)",
                       (cur.lastrowid, chat, base + 3))
    store.conn.commit()
    return cur.lastrowid


# ---- which moments ---------------------------------------------------------------------------------------
def test_moments_are_his_real_replies_newest_first_without_the_done_ones():
    s = Store(":memory:")
    a, b, c = seed(s, base=0), seed(s, base=10, trigger="random:1/25"), seed(s, base=20, outcome="error")
    seed(s, chat=5, base=30)  # a private chat is never training data
    s.conn.execute("INSERT INTO traces (kind, chat_id, msg_id, trigger, outcome, started) "
                   "VALUES ('learn', ?, 1, 'idle', 'sent', 1)", (C,))
    found = moments(s, done=set(), limit=10)
    assert [x.trace_id for x in found] == [b, a]
    assert found[0].direct is False and found[1].direct is True and found[1].reply == "nu jo"
    assert [x.trace_id for x in moments(s, done={b}, limit=10)] == [a]
    assert len(moments(s, done=set(), limit=1)) == 1


def test_a_moment_carries_the_groups_ratings_and_corrections():
    s = Store(":memory:")
    seed(s)
    s.set_feedback(C, 3, 111, 1, None, 2000.0)
    s.set_feedback(C, 3, 222, -1, "nuobodu", 2001.0)
    s.set_feedback(C, 3, 333, 1, None, 2002.0)
    s.conn.execute("INSERT INTO corrections (chat_id, msg_id, user_id, text, ts) VALUES (?,3,111,'senas',1)", (C,))
    s.conn.execute("INSERT INTO corrections (chat_id, msg_id, user_id, text, ts) VALUES (?,3,222,'naujas',2)", (C,))
    s.conn.commit()
    (m,) = moments(s, done=set(), limit=5)
    assert (m.up, m.down, m.corrections) == (2, 1, ["senas", "naujas"])


def test_serious_and_recall_moments_are_replayed_as_such():
    s = Store(":memory:")
    seed(s, trigger="serious")
    seed(s, base=10, trigger="recall")
    recall, serious = moments(s, done=set(), limit=5)
    assert (serious.serious, serious.recall, serious.direct) == (True, False, True)
    assert (recall.serious, recall.recall, recall.direct) == (False, True, True)


# ---- the chat as it was --------------------------------------------------------------------------------
def test_the_chat_is_replayed_as_it_was_before_his_reply():
    s = Store(":memory:")
    seed(s)
    s.conn.execute("INSERT INTO facts (kind, text, source, created, updated, emb, chat_id) "
                   "VALUES ('fact', 'senas faktas', 'learn', 500, 500, x'00', ?)", (C,))
    s.conn.execute("INSERT INTO facts (kind, text, source, created, updated, emb, chat_id) "
                   "VALUES ('fact', 'vėlesnis faktas', 'learn', 5000, 5000, x'00', ?)", (C,))
    s.conn.commit()
    (m,) = moments(s, done=set(), limit=1)
    then = as_of(s, m)
    texts = [r[0] for r in then.conn.execute("SELECT text FROM messages ORDER BY msg_id")]
    assert texts == ["rytoj perku nvidia", "botucha ka manai apie nvidia"]
    assert [r[0] for r in then.conn.execute("SELECT text FROM facts")] == ["senas faktas"]
    assert s.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 4  # the source is untouched


def test_the_judge_sees_the_lines_before_the_reply():
    s = Store(":memory:")
    seed(s)
    (m,) = moments(s, done=set(), limit=1)
    t = transcript(as_of(s, m), m)
    assert t == "Tadas: rytoj perku nvidia\nOna: botucha ka manai apie nvidia"


# ---- new replies -----------------------------------------------------------------------------------------
async def test_new_replies_are_made_from_that_moment_and_keep_their_prompt(tmp_path):
    s = Store(":memory:")
    seed(s)
    (m,) = moments(s, done=set(), limit=1)
    llm = FakeLLM(["pirmas variantas", "antras variantas"])
    cands = await generate(make_cfg(tmp_path), as_of(s, m), FakeEmbedder(), llm, m, n=2)
    assert [c.texts for c in cands] == [["pirmas variantas"], ["antras variantas"]]
    prompt = cands[0].prompt
    assert [x["role"] for x in prompt] == ["system", "user"]
    assert "botucha ka manai apie nvidia" in prompt[1]["content"]
    assert "VĖLIAU" not in prompt[1]["content"] and "nu jo" not in prompt[1]["content"]


async def test_a_failed_generation_is_no_candidate(tmp_path):
    s = Store(":memory:")
    seed(s)
    (m,) = moments(s, done=set(), limit=1)
    llm = FakeLLM([ConnectionError("down"), ConnectionError("down"), "gerai"])
    cands = await generate(make_cfg(tmp_path), as_of(s, m), FakeEmbedder(), llm, m, n=2)
    assert [c.texts for c in cands] == [["gerai"]]


# ---- choosing the example --------------------------------------------------------------------------------
P = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def scored(text, origin, score, ooc=0, problems=()):
    atoms = [Atom("x", i >= ooc) for i in range(max(ooc, 1))]
    return Scored(Candidate([text], P, origin), Verdict(score, atoms, ""), list(problems))


def moment(**kw):
    return Moment(**{"trace_id": 1, "chat_id": C, "msg_id": 2, "ts": 1.0, "reply": "tikras", "direct": True,
                     "serious": False, "recall": False, "up": 0, "down": 0, "corrections": [], **kw})


def test_a_correction_from_the_group_is_the_answer():
    ex = choose(moment(corrections=["taip reikėjo"]), [scored("a", "generated", 5)], min_score=4)
    assert (ex.source, ex.text) == ("correction", "taip reikėjo")


def test_the_best_clean_reply_wins():
    ex = choose(moment(), [scored("tikras", "original", 3), scored("geras", "generated", 5),
                           scored("blogas", "generated", 5, ooc=1), scored("ilgas", "generated", 5, problems=["too long"])],
                min_score=4)
    assert (ex.source, ex.text, ex.score) == ("generated", "geras", 5)


def test_nothing_good_enough_means_no_example():
    assert choose(moment(), [scored("a", "original", 3), scored("b", "generated", 2)], min_score=4) is None
    assert choose(moment(), [], min_score=4) is None


def test_a_reply_the_group_disliked_never_wins_and_a_liked_one_wins_ties():
    assert choose(moment(down=1), [scored("tikras", "original", 5)], min_score=4) is None
    ex = choose(moment(up=1), [scored("naujas", "generated", 5), scored("tikras", "original", 5)], min_score=4)
    assert ex.source == "original"


# ---- the whole night ------------------------------------------------------------------------------------
def make_db(tmp_path):
    path = tmp_path / "live.db"
    s = Store(path)
    seed(s, base=0)
    seed(s, base=10)
    s.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    s.conn.close()
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_a_night_writes_training_examples_and_a_report_and_leaves_the_db_alone(tmp_path):
    path = make_db(tmp_path)
    before = digest(path)
    out = tmp_path / "out"
    llm = FakeLLM(["variantas a", "variantas b", "variantas c", "variantas d"])
    judge = FakeLLM([verdict(5), verdict(3), verdict(2), verdict(4), verdict(2), verdict(1)])
    data, report = await run_night(make_cfg(tmp_path), path, FakeEmbedder(), llm, judge, out, limit=5, n=2,
                                   min_score=4, today="2026-11-24")
    assert digest(path) == before
    assert all(c["num_predict"] > 1 for c in llm.calls) and len(judge.calls) == 6  # all replies made, then judged
    rows = [json.loads(x) for x in data.read_text().splitlines()]
    assert len(rows) == 2
    newest, older = rows
    assert newest["source"] == "generated" and newest["messages"][-1] == {"role": "assistant", "content": "variantas a"}
    assert [x["role"] for x in newest["messages"]] == ["system", "user", "assistant"]
    assert [(c["origin"], c["score"]) for c in newest["candidates"]] == [("generated", 5), ("generated", 3),
                                                                        ("original", 2)]
    assert older["messages"][-1]["content"] == "variantas c" and older["score"] == 4
    text = report.read_text()
    assert "2/2" in text and "his real reply" in text


async def test_a_second_night_only_does_new_moments(tmp_path):
    path = make_db(tmp_path)
    out = tmp_path / "out"
    cfg = make_cfg(tmp_path)
    await run_night(cfg, path, FakeEmbedder(), FakeLLM(["a"] * 4), FakeLLM([verdict(5)] * 6), out,
                    limit=5, n=2, min_score=4, today="2026-11-24")
    llm = FakeLLM(["a"] * 4)
    data, _ = await run_night(cfg, path, FakeEmbedder(), llm, FakeLLM([verdict(5)] * 6), out,
                              limit=5, n=2, min_score=4, today="2026-11-25")
    assert llm.calls == [] and not data.exists()


async def test_a_broken_judge_skips_the_moment_but_marks_nothing_done(tmp_path):
    path = make_db(tmp_path)
    out = tmp_path / "out"
    cfg = make_cfg(tmp_path)
    await run_night(cfg, path, FakeEmbedder(), FakeLLM(["a"] * 4), FakeLLM([ConnectionError("x")] * 20), out,
                    limit=5, n=2, min_score=4, today="2026-11-24")
    llm = FakeLLM(["a"] * 4)
    await run_night(cfg, path, FakeEmbedder(), llm, FakeLLM([verdict(5)] * 6), out,
                    limit=5, n=2, min_score=4, today="2026-11-25")
    assert len(llm.calls) == 4  # tried again the next night


def test_the_live_db_is_opened_read_only(tmp_path):
    path = make_db(tmp_path)
    s = open_readonly(path)
    s.conn.execute("DELETE FROM messages")  # a copy in memory
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 8


# ---- unanswered messages, preference pairs, a night by the clock ---------------------------------------------
from botucha.nightly import backfill_pairs, pair_from_record, unanswered  # noqa: E402


def test_unanswered_messages_skip_his_answered_ones_commands_short_lines_and_bots():
    s = Store(":memory:")
    seed(s)  # msg 2 was answered by him
    add = lambda i, text, bot=False, chat=C: s.add_message(  # noqa: E731
        StoredMessage(chat, i, 111, "Tadas", 2000.0 + i, text, None, bot))
    add(50, "kas manot apie rytojaus rinką")
    add(51, "/gerai")
    add(52, "xdd")
    add(53, "[persiųsta iš kanalas] ilgas persiųstas tekstas čia")
    add(54, "kitas botas rašo ilgą žinutę", bot=True)
    add(55, "privačiai rašau ilgą žinutę", chat=5)
    found = unanswered(s, done=set(), limit=None)
    assert [(m.msg_id, m.direct, m.unanswered, m.key) for m in found][:1] == [(50, True, True, f"m{C}:50")]
    assert {m.msg_id for m in found} == {50, 4, 1}  # "VĖLIAU PARAŠYTA ŽINUTĖ" and "rytoj perku nvidia" too
    assert 50 not in {m.msg_id for m in unanswered(s, done={f"m{C}:50"}, limit=None)}


def rec(source, chosen, score, cands):
    return {"date": "d", "key": "1", "source": source, "score": score,
            "messages": P + [{"role": "assistant", "content": chosen}],
            "candidates": [{"origin": o, "text": t, "score": sc, "problems": pr, "ooc": []} for o, t, sc, pr in cands]}


def test_a_pair_is_the_example_against_the_worst_reply_with_a_clear_gap():
    r = rec("generated", "geras", 5, [("generated", "geras", 5, []), ("generated", "blogas", 2, []),
                                      ("original", "tikras", 4, [])])
    p = pair_from_record(r)
    assert (p["chosen"], p["rejected"], p["prompt"]) == ("geras", "blogas", P)
    assert pair_from_record(rec("generated", "a", 5, [("generated", "a", 5, []), ("generated", "b", 4, [])])) is None
    assert pair_from_record(rec("generated", "a", 5, [("generated", "a", 5, []),
                                                      ("generated", "b", 4, ["too long"])]))["rejected"] == "b"


def test_a_correction_is_preferred_over_his_real_reply():
    r = rec("correction", "pataisyta", None, [("generated", "x", 4, []), ("original", "tikras", 4, [])])
    assert pair_from_record(r)["rejected"] == "tikras"


async def test_a_night_with_unanswered_messages_writes_pairs_and_stops_at_the_deadline(tmp_path):
    path = make_db(tmp_path)
    out = tmp_path / "out"
    t = [0.0]
    llm = FakeLLM(["variantas a", "variantas b"] * 20)
    judge = FakeLLM([verdict(5), verdict(2), verdict(4)] * 20)

    def clock():
        t[0] += 1
        return t[0]
    data, report = await run_night(make_cfg(tmp_path), path, FakeEmbedder(), llm, judge, out, limit=None, n=2,
                                   min_score=4, today="2026-11-26", include_unanswered=True, batch=1,
                                   deadline=6.5, clock=clock)
    done = (out / "done.txt").read_text().split()
    assert 1 <= len(done) < 6  # stopped by the clock, every finished batch written
    rows = [json.loads(x) for x in data.read_text().splitlines()]
    pairs = [json.loads(x) for x in (out / "pairs-2026-11-26.jsonl").read_text().splitlines()]
    assert len(rows) == len(done) and pairs and pairs[0]["chosen"] == "variantas a"
    assert "preference pairs written" in report.read_text()


async def test_unanswered_moments_come_after_his_replies_and_have_no_real_reply(tmp_path):
    path = make_db(tmp_path)
    out = tmp_path / "out"
    llm = FakeLLM(["a", "b"] * 20)
    judge = FakeLLM([verdict(5)] * 60)
    data, _ = await run_night(make_cfg(tmp_path), path, FakeEmbedder(), llm, judge, out, limit=None, n=2,
                              min_score=4, today="2026-11-26", include_unanswered=True)
    rows = [json.loads(x) for x in data.read_text().splitlines()]
    kinds = [r["kind"] for r in rows]
    assert kinds[:2] == ["reply", "reply"] and set(kinds[2:]) == {"unanswered"}
    assert all("original" not in {c["origin"] for c in r["candidates"]} for r in rows if r["kind"] == "unanswered")


def test_backfill_pairs_from_old_examples_once(tmp_path):
    r = rec("generated", "geras", 5, [("generated", "geras", 5, []), ("generated", "blogas", 1, [])])
    (tmp_path / "examples-2026-11-24.jsonl").write_text(json.dumps(r) + "\n")
    (p,) = backfill_pairs(tmp_path)
    assert p.name == "pairs-2026-11-24.jsonl" and backfill_pairs(tmp_path) == []


# ---- a reply the admin approved with /gerai ----------------------------------------------------------------
def test_only_the_admins_thumbs_up_marks_a_reply_approved():
    s = Store(":memory:")
    seed(s)
    s.set_feedback(C, 3, 111, 1, None, 2000.0)  # a member's 👍 is a vote, not an approval
    (m,) = moments(s, done=set(), limit=1, admin_id=42)
    assert (m.up, m.boss_up) == (1, False)
    s.set_feedback(C, 3, 42, 1, None, 2001.0)
    (m,) = moments(s, done=set(), limit=1, admin_id=42)
    assert (m.up, m.boss_up) == (2, True)


def test_an_approved_reply_is_the_example_even_when_the_judge_disliked_it():
    ex = choose(moment(boss_up=True), [scored("tikras", "original", 2, ooc=1), scored("geras", "generated", 5)],
                min_score=4)
    assert (ex.source, ex.text, ex.score) == ("approved", "tikras", 2)
    corrected = choose(moment(boss_up=True, corrections=["taip"]), [scored("tikras", "original", 2)], min_score=4)
    assert corrected.source == "correction"  # a correction still says more than a 👍


def test_an_approved_reply_is_preferred_over_the_worst_other_with_no_gap_needed():
    r = rec("approved", "tikras", 3, [("original", "tikras", 3, []), ("generated", "a", 4, []),
                                      ("generated", "b", 3, [])])
    p = pair_from_record(r)
    assert (p["chosen"], p["rejected"], p["source"]) == ("tikras", "b", "approved")
