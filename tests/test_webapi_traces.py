"""Trace list/detail, message lookup, metrics and the live event stream."""
import asyncio
import json

from botucha.trace import Tracer
from botucha.webapi.metrics import compute_metrics
from botucha.webapi.routes_traces import live_events
from tests.test_app import C
from tests.webfix import web  # noqa: F401


def add_trace(store, *, started, duration_ms=100.0, outcome="sent", reply="labas", rejected=(), tok_s=8.0,
              sent=(), prompt="P"):
    perf = iter([0.0, duration_ms / 1000]).__next__
    run = Tracer(store, clock=lambda: started, perf=perf).start("reply", chat_id=C, msg_id=1, user_name="Tadas",
                                                              trigger="direct")
    run.add_step("prompt", detail={"persona": 10}, prompt=prompt)
    run.add_step("generation", name="attempt 1", detail={"tok_s": tok_s, "raw": reply})
    checks = [{"name": n, "ok": False, "reason": "x"} for n in rejected] or [{"name": "spelling", "ok": True}]
    run.add_step("filter", name="attempt 1", status="rejected" if rejected else "ok", detail={"checks": checks})
    run.finish(outcome, reply=reply, sent=sent)
    return run.id


async def test_trace_list_and_detail(web):
    client, deps, _ = await web()
    ids = [add_trace(deps.store, started=9_000.0 + i) for i in range(3)]
    listed = (await client.get("/api/traces")).json()
    assert [t["id"] for t in listed] == ids[::-1]
    assert listed[0]["attempts"] == 1 and listed[0]["trigger"] == "direct"
    older = (await client.get(f"/api/traces?before_id={ids[2]}&limit=1")).json()
    assert [t["id"] for t in older] == [ids[1]]
    detail = (await client.get(f"/api/traces/{ids[0]}")).json()
    assert detail["trace"]["id"] == ids[0]
    assert [s["kind"] for s in detail["steps"]] == ["prompt", "generation", "filter"]
    assert detail["steps"][0]["detail"] == {"persona": 10}
    assert [s["has_prompt"] for s in detail["steps"]] == [True, False, False]
    assert (await client.get(f"/api/traces/{ids[0]}/prompt")).json() == {"prompt": "P"}
    assert (await client.get("/api/traces/99999")).status_code == 404


async def test_trace_filters(web):
    client, deps, _ = await web()
    add_trace(deps.store, started=9_000.0, outcome="sent")
    add_trace(deps.store, started=9_001.0, outcome="canned")
    assert [t["outcome"] for t in (await client.get("/api/traces?outcome=canned")).json()] == ["canned"]
    assert (await client.get("/api/traces?kind=learn")).json() == []


async def test_by_message_lookup(web):
    client, deps, _ = await web()
    tid = add_trace(deps.store, started=9_000.0, sent=[(C, 5001)])
    assert (await client.get(f"/api/traces/by-message?chat_id={C}&msg_id=5001")).json() == {"trace_id": tid}
    assert (await client.get(f"/api/traces/by-message?chat_id={C}&msg_id=1")).json() == {"trace_id": None}


async def test_metrics_cards_and_percentiles(web):
    client, deps, _ = await web()
    now = 10_000.0
    for i, d in enumerate([100, 200, 300, 400, 1000]):
        add_trace(deps.store, started=now - 60 - i, duration_ms=d, rejected=("spelling",) if i == 0 else ())
    add_trace(deps.store, started=now - 30, outcome="canned", duration_ms=50)
    deps.store.set_feedback(C, 1, 111, 1, None, now - 10)
    deps.store.set_feedback(C, 2, 111, -1, "blogai", now - 10)
    m = compute_metrics(deps.store, now, "24h")
    assert m["cards"]["replies"] == 5 and m["cards"]["median_ms"] == 300
    assert m["cards"]["good"] == 1 and m["cards"]["bad"] == 1 and m["cards"]["rejections"] == 1
    assert m["cards"]["tok_s"] == 8.0
    bucket = next(b for b in m["series"] if b["replies"])
    assert bucket["p50_ms"] == 300 and bucket["p95_ms"] == 1000
    assert m["rejections_by_filter"] == {"spelling": 1}
    assert len(m["series"]) == 24 and sum(r["good"] for r in m["ratings"]) == 1
    assert (await client.get("/api/metrics?range=7d")).json()["series"].__len__() == 7
    assert (await client.get("/api/metrics?range=1y")).status_code == 422


async def test_live_emits_new_trace(web):
    _, deps, _ = await web()
    add_trace(deps.store, started=9_000.0)  # existing traces are not replayed

    async def status():
        return {"bot": "active"}
    events = live_events(deps.store, status, poll_s=0.01, status_every_s=1000)
    first = await asyncio.wait_for(anext(events), 1)
    assert first.startswith("event: status")
    tid = add_trace(deps.store, started=9_100.0)
    ev = await asyncio.wait_for(anext(events), 3)
    assert ev.startswith("event: trace\n")
    assert json.loads(ev.split("data: ", 1)[1])["id"] == tid
    await events.aclose()


async def test_live_waits_until_trace_finished(web):
    _, deps, _ = await web()

    async def status():
        return {}
    events = live_events(deps.store, status, poll_s=0.01, status_every_s=1000)
    await anext(events)
    run = Tracer(deps.store).start("reply")
    nxt = asyncio.ensure_future(anext(events))
    await asyncio.sleep(0.05)
    assert not nxt.done()  # still running: not sent yet
    run.finish("sent", reply="x")
    ev = await asyncio.wait_for(nxt, 2)
    assert json.loads(ev.split("data: ", 1)[1])["outcome"] == "sent"
    await events.aclose()


async def test_live_keeps_up_after_many_traces_and_a_stuck_one(web):
    _, deps, _ = await web()

    async def status():
        return {}
    events = live_events(deps.store, status, poll_s=0.0, status_every_s=1000, clock=lambda: 10_000.0)
    await anext(events)
    Tracer(deps.store, clock=lambda: 1_000.0).start("reply")  # crashed long ago, never finished
    for i in range(250):
        add_trace(deps.store, started=9_000.0 + i)
    got = [json.loads((await asyncio.wait_for(anext(events), 2)).split("data: ", 1)[1])["id"] for _ in range(250)]
    tid = add_trace(deps.store, started=9_999.0)
    nxt = json.loads((await asyncio.wait_for(anext(events), 2)).split("data: ", 1)[1])["id"]
    assert len(set(got)) == 250 and nxt == tid
    await events.aclose()


async def test_live_emits_a_trace_that_was_running_when_connected(web):
    _, deps, _ = await web()

    async def status():
        return {}
    run = Tracer(deps.store, clock=lambda: 9_990.0).start("reply")  # running when the page connects
    events = live_events(deps.store, status, poll_s=0.01, status_every_s=1000, clock=lambda: 10_000.0)
    await anext(events)
    run.finish("sent", reply="x")
    ev = await asyncio.wait_for(anext(events), 2)
    assert json.loads(ev.split("data: ", 1)[1])["id"] == run.id
    await events.aclose()
