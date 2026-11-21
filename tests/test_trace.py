"""Trace storage, the Tracer and old-database migration."""
import os
import sqlite3

import pytest

from botucha.store import Store
from botucha.trace import NULL_RUN, Tracer, prune_traces

DAY = 86_400.0


def test_run_records_steps_in_order_with_durations():
    store = Store(":memory:")
    t = iter([0.0, 0.010, 0.030, 0.040, 0.050]).__next__
    run = Tracer(store, clock=lambda: 100.0, perf=t).start("reply", chat_id=-1, msg_id=7, user_name="Tadas",
                                                         trigger="direct")
    with run.step("retrieval") as s:
        s.detail["facts"] = [{"id": 1, "score": 0.8}]
    run.add_step("filter", status="rejected", detail={"checks": [{"name": "repeat", "ok": False}]})
    run.finish("sent", reply="labas", sent=[(-1, 5001)])
    tr = store.conn.execute("SELECT kind, trigger, outcome, reply FROM traces").fetchone()
    assert tr == ("reply", "direct", "sent", "labas")
    steps = store.conn.execute("SELECT seq, kind, status, duration_ms, detail FROM trace_steps ORDER BY seq").fetchall()
    assert [s[:3] for s in steps] == [(0, "retrieval", "ok"), (1, "filter", "rejected")]
    assert steps[0][3] == pytest.approx(20.0)
    assert '"score": 0.8' in steps[0][4]
    assert store.conn.execute("SELECT trace_id FROM trace_messages WHERE msg_id=5001").fetchone()[0] == run.id


def test_step_error_is_recorded_and_reraised():
    run = Tracer(Store(":memory:")).start("reply")
    with pytest.raises(ValueError):
        with run.step("generation"):
            raise ValueError("boom")
    status, detail = run.store.conn.execute("SELECT status, detail FROM trace_steps").fetchone()
    assert status == "error" and "boom" in detail


def test_tracer_db_failure_never_raises():
    store = Store(":memory:")
    run = Tracer(store).start("reply")
    store.conn.close()
    with run.step("context"):
        pass
    run.add_step("filter")
    run.finish("sent")


def test_null_run_does_nothing():
    with NULL_RUN.step("context") as s:
        s.detail["x"] = 1
    NULL_RUN.add_step("filter")
    NULL_RUN.finish("sent")
    assert NULL_RUN.id is None


def test_prune_keeps_recent_and_drops_old_prompts():
    store = Store(":memory:")
    run = Tracer(store, clock=lambda: 0.0).start("reply")
    run.add_step("prompt", prompt="SYSTEM PROMPT")
    run.finish("sent")
    prune_traces(store, 8 * DAY)
    assert store.conn.execute("SELECT prompt FROM trace_steps").fetchone()[0] is None
    assert store.conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 1
    assert prune_traces(store, 31 * DAY) == 1
    for table in ("traces", "trace_steps", "trace_messages"):
        assert store.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_migrates_old_database(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE feedback (chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            score INTEGER NOT NULL, reason TEXT, ts REAL NOT NULL, PRIMARY KEY (chat_id, msg_id, user_id));
        CREATE TABLE corrections (chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            text TEXT NOT NULL, ts REAL NOT NULL, PRIMARY KEY (chat_id, msg_id, user_id));
        INSERT INTO feedback VALUES (1, 2, 3, -1, 'blogai', 0);
        INSERT INTO corrections VALUES (1, 2, 3, 'taip', 0);
    """)
    db.commit()
    db.close()
    store = Store(path)
    assert store.conn.execute("SELECT score, reviewed FROM feedback").fetchone() == (-1, 0)
    assert store.conn.execute("SELECT text, reviewed FROM corrections").fetchone() == ("taip", 0)
    assert store.conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 0
    assert store.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    Store(path)  # migrating twice is harmless
    assert os.path.exists(path)
