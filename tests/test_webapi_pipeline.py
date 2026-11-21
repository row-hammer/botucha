"""Pipeline page: each reply's path through the filter, stage timings, rates, drill-down and live progress."""
import asyncio
import json

import pytest

from botucha.store import Store
from botucha.trace import Tracer
from botucha.webapi.pipeline import compute_pipeline, reply_path
from botucha.webapi.routes_traces import live_events
from tests.webfix import web  # noqa: F401

NOW = 10_000.0


@pytest.fixture
def web_store():
    return Store(":memory:")


def run_reply(store, *, attempts, outcome, trigger="direct", started=9_000.0, ms=None):
    """attempts: list of "ok", "error" (generation failed) or a failed check name."""
    ms = ms or {}
    run = Tracer(store, clock=lambda: started).start("reply", user_name="Tadas", trigger=trigger)
    for kind in ("context", "retrieval", "prompt"):
        run.add_step(kind, duration_ms=ms.get(kind, 10.0))
    for i, a in enumerate(attempts, 1):
        name = f"attempt {i}"
        if a == "error":
            run.add_step("generation", name=name, status="error", duration_ms=5.0, detail={"error": "boom"})
            continue
        run.add_step("generation", name=name, duration_ms=ms.get(f"gen{i}", 1000.0), detail={"tok_s": 7.0})
        checks = [{"name": "empty", "ok": True}]
        if a != "ok":
            checks.append({"name": a, "ok": False, "reason": "x"})
        run.add_step("filter", name=name, status="ok" if a == "ok" else "rejected", duration_ms=ms.get("filter", 2.0),
                     detail={"checks": checks})
    if outcome in ("sent", "fallback"):
        run.add_step("send", duration_ms=ms.get("send", 100.0))
    run.finish(outcome, reply="x")
    return run.id


def steps_of(store, tid):
    return store.conn.execute("SELECT kind, name, status, detail FROM trace_steps WHERE trace_id=? ORDER BY seq",
                              (tid,)).fetchall()


def test_path_first_try(web_store):
    tid = run_reply(web_store, attempts=["ok"], outcome="sent")
    assert reply_path("sent", "direct", steps_of(web_store, tid)) == ["trigger:direct", "a1:ok", "out:sent"]


def test_path_rejected_then_fallback(web_store):
    tid = run_reply(web_store, attempts=["spelling", "repeat"], outcome="fallback", trigger="serious")
    assert reply_path("fallback", "serious", steps_of(web_store, tid)) == [
        "trigger:serious", "a1:spelling", "a2:repeat", "out:fallback"]


def test_path_generation_error_then_ok(web_store):
    tid = run_reply(web_store, attempts=["error", "ok"], outcome="sent")
    assert reply_path("sent", "direct", steps_of(web_store, tid)) == ["trigger:direct", "a1:error", "a2:ok", "out:sent"]


def test_path_without_generation_and_old_details():
    # a canned reply has no generation; an old trace may have a filter with no checks list
    assert reply_path("canned", "recall", []) == ["trigger:recall", "out:canned"]
    assert reply_path("fallback", "", [("filter", "attempt 1", "rejected", "{}")]) == [
        "trigger:unknown", "a1:rejected", "out:fallback"]
    assert reply_path("sent", "direct", [("filter", "attempt 1", "ok", "not json")]) == [
        "trigger:direct", "a1:ok", "out:sent"]


def test_pipeline_flow_rates_and_stages(web_store):
    run_reply(web_store, attempts=["ok"], outcome="sent", ms={"gen1": 1000.0})
    run_reply(web_store, attempts=["spelling", "ok"], outcome="sent", ms={"gen1": 1000.0, "gen2": 3000.0})
    run_reply(web_store, attempts=["spelling", "spelling"], outcome="fallback")
    run_reply(web_store, attempts=["error", "error"], outcome="skipped")
    Tracer(web_store, clock=lambda: 9_500.0).start("reply")  # still running: not counted
    Tracer(web_store, clock=lambda: 9_500.0).start("learn").finish("sent")  # other kinds: not counted
    p = compute_pipeline(web_store, NOW, "24h")
    assert p["rates"] == {"runs": 4, "sent": 2, "fallback": 1, "silent": 1, "first_try": 1, "avg_attempts": 1.75}
    links = {(lk["source"], lk["target"]): lk["value"] for lk in p["links"]}
    assert links[("trigger:direct", "a1:ok")] == 1 and links[("trigger:direct", "a1:spelling")] == 2
    assert links[("a1:spelling", "a2:ok")] == 1 and links[("a1:spelling", "a2:spelling")] == 1
    assert links[("a2:spelling", "out:fallback")] == 1 and links[("a2:error", "out:skipped")] == 1
    assert {n["id"]: n["n"] for n in p["nodes"]}["a1:spelling"] == 2
    bucket = [s for s in p["stages"] if s["n"]][0]  # mean over the 3 replies that were sent
    assert bucket["n"] == 3 and bucket["gen1"] == 1000.0 and bucket["gen2"] == round((3000 + 1000) / 3, 1)
    assert bucket["context"] == 10.0 and bucket["send"] == 100.0


def test_pipeline_empty_range(web_store):
    p = compute_pipeline(web_store, NOW, "7d")
    assert p["rates"]["runs"] == 0 and p["rates"]["avg_attempts"] is None
    assert p["nodes"] == [] and p["links"] == [] and len(p["stages"]) == 7


async def test_pipeline_endpoint_and_path_drilldown(web):
    client, deps, _ = await web(clock=lambda: NOW)
    a = run_reply(deps.store, attempts=["spelling", "ok"], outcome="sent")
    run_reply(deps.store, attempts=["ok"], outcome="sent")
    b = run_reply(deps.store, attempts=["spelling", "spelling"], outcome="fallback")
    body = (await client.get("/api/pipeline?range=24h")).json()
    assert body["rates"]["runs"] == 3
    got = (await client.get("/api/traces?path=a1:spelling&range=24h")).json()
    assert [t["id"] for t in got] == [b, a]
    assert (await client.get("/api/traces?path=out:fallback&range=24h")).json()[0]["id"] == b
    assert (await client.get("/api/pipeline?range=1y")).status_code == 422


async def test_live_reports_progress_of_a_running_reply(web):
    _, deps, _ = await web()

    async def status():
        return {}
    events = live_events(deps.store, status, poll_s=0.01, status_every_s=1000, clock=lambda: NOW)
    await anext(events)
    run = Tracer(deps.store, clock=lambda: 9_990.0).start("reply", user_name="Tadas", trigger="direct")
    run.add_step("context")
    ev = await asyncio.wait_for(anext(events), 2)
    assert ev.startswith("event: progress")
    data = json.loads(ev.split("data: ", 1)[1])
    assert data["id"] == run.id and data["last"] == {"kind": "context", "name": None, "status": "ok"}
    assert data["steps"] == 1 and data["user_name"] == "Tadas"
    run.add_step("retrieval")
    data = json.loads((await asyncio.wait_for(anext(events), 2)).split("data: ", 1)[1])
    assert data["last"]["kind"] == "retrieval" and data["steps"] == 2
    run.finish("sent", reply="x")
    assert (await asyncio.wait_for(anext(events), 2)).startswith("event: trace")
    await events.aclose()
