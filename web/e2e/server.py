"""Dashboard test server for the Playwright suite: the real API and built UI over a throwaway database
filled with invented data, a fake systemd (no real service is touched) and a fake embedder (no Ollama).

    uv run python web/e2e/server.py --port 8799
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

from botucha.config import load_config  # noqa: E402
from botucha.memory import Memory  # noqa: E402
from botucha.store import Store, StoredMessage  # noqa: E402
from botucha.trace import Tracer  # noqa: E402
from botucha.webapi.app import Deps, create_app  # noqa: E402
from tests.fakes import FakeEmbedder  # noqa: E402
from tests.webfix import FakeService  # noqa: E402

CHAT = -100
PEOPLE = [(11, "Tadas"), (12, "Rūta"), (13, "Mantas")]
BOT = 99


def reply(store: Store, *, who: str, started: float, attempts: list[str], outcome: str, trigger: str = "direct",
          claude: str | None = None, sent: int | None = None) -> None:
    """attempts: "ok", "error" or a list of invented words that fail the spell check."""
    perf = iter([0.0, 21.0]).__next__
    run = Tracer(store, clock=lambda: started, perf=perf).start("reply", chat_id=CHAT, msg_id=1, user_name=who,
                                                              trigger=trigger)
    run.add_step("context", duration_ms=40, detail={"history": 22})
    run.add_step("retrieval", duration_ms=350, detail={"query": "kaip sekasi", "facts": [{"id": 1, "text": "x"}],
                                                       "chunks": [{"first_msg_id": 1, "preview": "Tadas: labas"}]})
    run.add_step("prompt", detail={"persona": 4000, "style": 900, "approx_tokens": 6200}, prompt="(test prompt)")
    for i, a in enumerate(attempts, 1):
        name = f"attempt {i}"
        if a == "error":
            run.add_step("generation", name=name, status="error", duration_ms=50, detail={"error": "timeout"})
            continue
        run.add_step("generation", name=name, duration_ms=15_000,
                     detail={"model": "test-model", "prompt_eval_count": 6400, "eval_count": 30, "tok_s": 6.9,
                             "raw": "nu na, viskas gerai"})
        checks = [{"name": "empty", "ok": True, "reason": ""}]
        checks.append({"name": "spelling", "ok": a == "ok", "reason": "" if a == "ok" else a})
        run.add_step("filter", name=name, status="ok" if a == "ok" else "rejected", detail={"checks": checks})
        if i == 1 and claude:
            run.add_step("proofread", status="error" if claude == "error" else "ok", duration_ms=3_000,
                         detail={"error": "timeout"} if claude == "error" else
                         {"model": "claude-opus-5-5", "fixed": [["nužvalgai", "nužvelgei"]], "kept": []})
            if claude == "ok":
                run.add_step("filter", name="proofread", detail={"checks": [{"name": "spelling", "ok": True}]})
                break
    if outcome in ("sent", "fallback"):
        run.add_step("send", duration_ms=400, detail={"msg_ids": [sent or 0]})
    run.finish(outcome, reply="nu na, viskas gerai xddd", sent=[(CHAT, sent)] if sent else ())


async def seed(store: Store, mem: Memory, now: float) -> None:
    for uid, name in PEOPLE:
        store.upsert_member(uid, name, None)
    for i in range(120):  # a week of invented chat
        uid, name = PEOPLE[i % 3]
        store.add_message(StoredMessage(CHAT, 1000 + i, uid, name, now - i * 4_800, f"žinutė {i} apie akcijas"))
    store.add_message(StoredMessage(CHAT, 2000, BOT, "Botucha", now - 500, "nu na xddd", is_bot=True))
    t = mem.add_person("Tadas", ["tadas", "tado"], 11)
    mem.add_person("Rūta", ["rūta"], 12)
    mem.add_person("Jonas", ["jonas"])
    mem.add_relation("Tadas", "draugas", "Jonas", "test")
    await mem.add_fact("fact", "Tadas dirba banke", t, "test")
    await mem.add_fact("slang", "tsg = tiesiog", None, "test")
    mem.set_profile(11, "Mėgsta akcijas ir dviračius.")
    reply(store, who="Tadas", started=now - 3_000, attempts=["ok"], outcome="sent", sent=2000)
    reply(store, who="Rūta", started=now - 2_500, attempts=["nužvalgai"], outcome="sent", claude="ok")
    reply(store, who="Mantas", started=now - 2_000, attempts=["susitarpė", "glichiuoja"], outcome="fallback",
          claude="error", trigger="serious")
    reply(store, who="Tadas", started=now - 1_500, attempts=["error", "ok"], outcome="sent", trigger="keyword:spx")
    reply(store, who="Rūta", started=now - 90_000, attempts=["skrietėti", "ok"], outcome="sent")
    Tracer(store, clock=lambda: now - 1_000).start("learn", trigger="idle").finish("sent", reply="1 new")
    store.conn.execute("INSERT INTO feedback (chat_id, msg_id, user_id, score, ts) VALUES (?, 2000, 12, 1, ?)",
                       (CHAT, now - 400))
    store.conn.execute("INSERT INTO spell_fixes (ts, word, verdict, fix) VALUES (?, 'nužvalgai', 'fix', 'nužvelgei')",
                       (now - 2_400,))
    store.conn.execute("INSERT INTO spell_fixes (ts, word, verdict, fix) VALUES (?, 'glichiuoja', 'keep', NULL)",
                       (now - 1_900,))
    store.conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8799)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="botucha-e2e-"))
    shutil.copy(ROOT / "config.example.toml", tmp / "config.toml")
    (tmp / "persona.md").write_text("Tu esi Botucha, testinis personažas.\n")
    (tmp / "style_examples.txt").write_text("Tadas: nu na\n")
    cfg = load_config(tmp / "config.toml", {"BOTUCHA_TOKEN": "test"})
    store = Store(cfg.paths.db)
    mem = Memory(store, FakeEmbedder())
    now = time.time()
    asyncio.run(seed(store, mem, now))
    deps = Deps(cfg=cfg, config_path=tmp / "config.toml", store=store, memory=mem, service=FakeService(),
                static_dir=ROOT / "web" / "out", backups_dir=tmp / "backups")
    app = create_app(deps, port=args.port)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
