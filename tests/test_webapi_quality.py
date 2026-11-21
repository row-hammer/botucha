"""Quality page: flagged words, attempts, trigger mix, per-person table, context use and group activity."""
import datetime as dt

import pytest

from botucha.store import Store, StoredMessage
from botucha.trace import Tracer
from botucha.webapi.quality import compute_quality
from tests.webfix import web  # noqa: F401

NOW = 1_795_300_000.0  # a Saturday, 2026-11-21 (UTC)
UTC = dt.timezone.utc


@pytest.fixture
def store():
    return Store(":memory:")


def reply(store, *, who="Tadas", trigger="direct", flagged=(), outcome="sent", started=NOW - 600, ms=20_000.0,
          prompt_tokens=7000, facts=2, chunks=3, history=20, msg_id=None):
    """flagged: one tuple of unknown words per rejected attempt; a final passing attempt is added
    unless the outcome is a fallback."""
    perf = iter([0.0, ms / 1000]).__next__
    run = Tracer(store, clock=lambda: started, perf=perf).start("reply", user_name=who, trigger=trigger)
    run.add_step("context", detail={"history": history})
    run.add_step("retrieval", detail={"facts": [{"id": i} for i in range(facts)],
                                      "chunks": [{"first_msg_id": i} for i in range(chunks)]})
    attempts = [list(w) for w in flagged] + ([] if outcome == "fallback" else [None])
    for i, words in enumerate(attempts, 1):
        run.add_step("generation", name=f"attempt {i}", detail={"prompt_eval_count": prompt_tokens, "tok_s": 7.0})
        checks = [{"name": "empty", "ok": True, "reason": ""}]
        checks.append({"name": "spelling", "ok": not words, "reason": ", ".join(words or [])})
        run.add_step("filter", name=f"attempt {i}", status="rejected" if words else "ok", detail={"checks": checks})
    run.finish(outcome, reply="x", sent=[(-1, msg_id)] if msg_id else ())
    return run.id


def test_flagged_words_ranked_with_last_trace(store):
    reply(store, flagged=[("glichiuoja", "nusibudai")], started=NOW - 900)
    last = reply(store, flagged=[("Glichiuoja",), ("glichiuoja",)], outcome="fallback", started=NOW - 300)
    q = compute_quality(store, NOW, "24h", num_ctx=32768, tz=UTC)
    assert q["words"][0] == {"word": "glichiuoja", "n": 3, "traces": 2, "last": NOW - 300, "trace_id": last}
    assert q["words"][1]["word"] == "nusibudai" and q["words"][1]["n"] == 1


def test_attempts_and_trigger_mix(store):
    reply(store)
    reply(store, flagged=[("x",)])
    reply(store, flagged=[("x",), ("y",)], outcome="fallback", trigger="serious")
    reply(store, trigger="keyword:spx+random:1/25")
    q = compute_quality(store, NOW, "24h", num_ctx=32768, tz=UTC)
    assert q["attempts"] == {"1": 2, "2": 2}
    assert q["triggers"] == {"direct": 2, "serious": 1, "keyword": 1, "random": 1}


def test_people_table_with_ratings_on_replies_to_them(store):
    store.add_message(StoredMessage(-1, 500, 9, "Botucha", NOW - 100, "atsakymas", is_bot=True))
    reply(store, who="Tadas", msg_id=500, ms=10_000.0)
    reply(store, who="Tadas", flagged=[("x",), ("y",)], outcome="fallback", ms=30_000.0)
    reply(store, who="Rūta", outcome="skipped", flagged=[("x",), ("y",)])
    store.conn.execute("INSERT INTO feedback (chat_id, msg_id, user_id, score, ts) VALUES (-1, 500, 7, 1, ?)", (NOW,))
    store.conn.execute("INSERT INTO feedback (chat_id, msg_id, user_id, score, ts) VALUES (-1, 500, 8, -1, ?)", (NOW,))
    q = compute_quality(store, NOW, "24h", num_ctx=32768, tz=UTC)
    people = {p["name"]: p for p in q["people"]}
    assert people["Tadas"] == {"name": "Tadas", "runs": 2, "sent": 1, "fallback": 1, "silent": 0,
                               "median_ms": 10_000.0, "good": 1, "bad": 1}
    assert people["Rūta"]["silent"] == 1 and people["Rūta"]["median_ms"] is None
    assert q["people"][0]["name"] == "Tadas"  # most runs first


def test_context_use_against_the_window(store):
    for tokens, facts in ((6000, 1), (8000, 3), (30_000, 5)):
        reply(store, prompt_tokens=tokens, facts=facts, chunks=2, history=10)
    c = compute_quality(store, NOW, "24h", num_ctx=32768, tz=UTC)["context"]
    assert c == {"limit": 32768, "p50": 8000, "p95": 30_000, "max": 30_000, "replies": 3,
                 "facts": 3.0, "chunks": 2.0, "history": 10.0}


def test_activity_heatmap_in_local_time(store):
    sat_10 = dt.datetime(2026, 11, 21, 10, 15, tzinfo=UTC).timestamp()
    for i in range(3):
        store.add_message(StoredMessage(-1, i, 5, "Tadas", sat_10 + i, "labas"))
    store.add_message(StoredMessage(-1, 99, 9, "Botucha", sat_10, "bot", is_bot=True))  # not counted
    q = compute_quality(store, NOW, "7d", num_ctx=32768, tz=UTC)
    assert len(q["activity"]) == 7 and all(len(row) == 24 for row in q["activity"])
    assert q["activity"][5][10] == 3 and sum(map(sum, q["activity"])) == 3  # Monday = 0


def test_old_or_odd_traces_do_not_break_it(store):
    run = Tracer(store, clock=lambda: NOW - 60).start("reply", trigger="")
    run.add_step("filter", name="attempt 1", status="rejected", detail={"checks": "not a list"})
    run.add_step("generation", name="attempt 1", detail={"prompt_eval_count": "?"})
    run.finish("fallback")
    q = compute_quality(store, NOW, "24h", num_ctx=32768, tz=UTC)
    assert q["words"] == [] and q["context"]["p50"] is None and q["triggers"] == {"unknown": 1}


async def test_quality_endpoint(web):
    client, deps, _ = await web(clock=lambda: NOW)
    reply(deps.store, flagged=[("glichiuoja",)])
    body = (await client.get("/api/quality?range=24h")).json()
    assert body["words"][0]["word"] == "glichiuoja" and body["context"]["limit"] == deps.cfg.model.num_ctx
    assert (await client.get("/api/quality?range=2d")).status_code == 422
