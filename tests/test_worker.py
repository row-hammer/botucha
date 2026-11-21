import asyncio

import pytest

from botucha.worker import Job, ReplyWorker


def job(i, direct=True):
    return Job(chat_id=-1, msg_id=i, direct=direct, serious=False, recall=False)


@pytest.fixture
async def setup():
    batches: list[list[Job]] = []
    gate = {"block": None, "fail": False}

    async def run_job(jobs):
        batches.append(jobs)
        if gate["fail"]:
            gate["fail"] = False
            raise RuntimeError("boom")
        if gate["block"]:
            await gate["block"].wait()

    w = ReplyWorker(run_job, quiet_s=0.05, max_wait_s=0.2)
    task = asyncio.create_task(w.run())
    yield w, batches, gate
    await w.stop()
    task.cancel()


async def test_burst_merged(setup):
    w, batches, _ = setup
    for i in range(3):
        w.submit(job(i))
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.15)
    assert [len(b) for b in batches] == [3]


async def test_waits_for_quiet():
    # Own worker with wide windows: GC pauses of tens of ms in a long test run must not look like "quiet".
    batches = []

    async def run_job(jobs):
        batches.append(jobs)

    w = ReplyWorker(run_job, quiet_s=0.3, max_wait_s=2.0)
    task = asyncio.create_task(w.run())
    loop = asyncio.get_running_loop()
    start = loop.time()
    w.submit(job(1))
    while loop.time() - start < 0.8:  # chat keeps going for 0.8 s
        await asyncio.sleep(0.02)
        w.activity()
    assert batches == []
    await asyncio.sleep(0.5)
    assert len(batches) == 1
    await w.stop()
    task.cancel()


async def test_max_wait_caps_delay(setup):
    w, batches, _ = setup
    w.submit(job(1))
    for _ in range(15):  # 300 ms of constant activity
        await asyncio.sleep(0.02)
        w.activity()
    assert len(batches) == 1


async def test_jobs_during_run_go_to_next_batch(setup):
    w, batches, gate = setup
    gate["block"] = asyncio.Event()
    w.submit(job(1))
    await asyncio.sleep(0.1)
    assert len(batches) == 1
    w.submit(job(2))
    w.submit(job(3))
    gate["block"].set()
    await asyncio.sleep(0.15)
    assert [[j.msg_id for j in b] for b in batches] == [[1], [2, 3]]


async def test_exception_does_not_kill_loop(setup):
    w, batches, gate = setup
    gate["fail"] = True
    w.submit(job(1))
    await asyncio.sleep(0.1)
    w.submit(job(2))
    await asyncio.sleep(0.1)
    assert len(batches) == 2


async def test_pending_flag(setup):
    w, batches, _ = setup
    assert w.pending is False
    w.submit(job(1))
    assert w.pending is True
    await asyncio.sleep(0.15)
    assert w.pending is False


async def test_drain_finishes_the_running_batch_and_what_is_queued(setup):
    w, batches, gate = setup
    gate["block"] = asyncio.Event()
    w.submit(job(1))
    await asyncio.sleep(0.1)  # batch 1 is running and blocked
    w.submit(job(2))          # queued behind it, still inside its quiet wait
    asyncio.get_running_loop().call_later(0.05, gate["block"].set)
    left = await w.drain(timeout_s=2)
    assert left == [] and [[j.msg_id for j in b] for b in batches] == [[1], [2]]


async def test_drain_does_not_wait_out_the_burst_timer(setup):
    w, batches, _ = setup
    w.quiet_s = w.max_wait_s = 30  # would wait half a minute for the chat to go quiet
    w.submit(job(1))
    left = await asyncio.wait_for(w.drain(timeout_s=5), 1)
    assert left == [] and len(batches) == 1


async def test_drain_gives_back_what_it_could_not_finish(setup):
    w, batches, gate = setup
    gate["block"] = asyncio.Event()  # never released: the reply hangs
    w.submit(job(1))
    await asyncio.sleep(0.1)
    w.submit(job(2))
    left = await w.drain(timeout_s=0.1)
    assert [j.msg_id for j in left] == [1, 2]  # the hung one and the one behind it


async def test_after_drain_new_jobs_are_not_taken(setup):
    w, batches, _ = setup
    await w.drain(timeout_s=1)
    w.submit(job(9))
    await asyncio.sleep(0.1)
    assert batches == []
