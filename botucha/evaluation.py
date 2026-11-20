"""Persona and memory evaluation.

  uv run python -m botucha.evaluation persona --config config.toml [--model NAME]
  uv run python -m botucha.evaluation memory  --config config.toml
  uv run python -m botucha.evaluation bootstrap --config config.toml   (load the export into the DB now)

Both read the real memory DB but never change it (each prompt runs on an in-memory copy).
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import os
import random
import re
import time
import tomllib
from datetime import date
from pathlib import Path

from .app import Botucha, ReplyJob
from .config import load_config
from .embed import OllamaEmbedder
from .llm import OllamaLLM
from .memory import Memory
from .store import Store, StoredMessage

DIACRITICS = re.compile(r"[ąčęėįšųūž]", re.IGNORECASE)
EVAL_USER, EVAL_NAME = 1, "eval"


def check_reply(texts: list[str], member_names: list[str], serious: bool = False) -> list[str]:
    if not texts:
        return ["empty"]
    problems = []
    if not serious and any(len(t.split()) > 15 for t in texts):
        problems.append("too long")
    if sum(bool(DIACRITICS.search(t)) for t in texts) / len(texts) > 0.3:
        problems.append("diacritics")
    names = {n.lower() for n in member_names}
    if any(t.split(":", 1)[0].strip().lower() in names for t in texts if ":" in t):
        problems.append("impersonation")
    return problems


class CaptureOutbox:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, chat_id, texts, reply_to):
        self.sent += texts
        return [10**9 + len(self.sent)]

    async def react(self, chat_id, msg_id, emoji):
        pass

    async def typing(self, chat_id):
        pass


async def _nosleep(_):
    return None


def _copy(store: Store) -> Store:
    mem = Store(":memory:")
    store.conn.backup(mem.conn)
    return mem


async def run_persona(cfg, prompts: list[dict], out_dir: Path) -> Path:
    base = Store(cfg.paths.db)
    chat_id = cfg.telegram.chat_ids[-1]
    embedder = OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model)
    llm = OllamaLLM(cfg.model)
    lines = [f"# Persona eval: {cfg.model.chat_model} ({date.today()})", ""]
    for i, p in enumerate(prompts):
        store = _copy(base)
        out = CaptureOutbox()
        bot = Botucha(cfg, store, Memory(store, embedder), llm, out, rng=random.Random(i),
                      bot_user_id=0, bot_username="botucha_bot", sleep=_nosleep, started_at=0)
        msg_id = 10**9
        store.add_message(StoredMessage(chat_id, msg_id, EVAL_USER, EVAL_NAME, time.time(), p["text"]))
        t = time.time()
        await bot.run_job([ReplyJob(chat_id, msg_id, direct=True, serious=bool(p.get("serious")), recall=False)])
        secs = time.time() - t
        problems = check_reply(out.sent, bot._member_names(), serious=bool(p.get("serious")))
        lines += [f"## {p['name']}", f"> {p['text']}", "", *[f"    {s}" for s in out.sent], "",
                  f"*{secs:.1f}s*" + (f" — **problems: {', '.join(problems)}**" if problems else ""), ""]
        print(f"{p['name']}: {problems or 'ok'} ({secs:.1f}s)", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date.today()}-{cfg.model.chat_model.replace(':', '_')}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def run_memory(cfg, queries: list[str]) -> None:
    store = Store(cfg.paths.db)
    mem = Memory(store, OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model))
    for q in queries:
        hits = await mem.search_chunks(q, k=1)
        top = hits[0].chunk.text.replace("\n", " | ")[:160] if hits else "(nothing)"
        print(f"{q}\n  -> {top}\n")


async def run_bootstrap(cfg) -> None:
    store = Store(cfg.paths.db)
    mem = Memory(store, OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model))
    bot = Botucha(cfg, store, mem, OllamaLLM(cfg.model), CaptureOutbox(), rng=random.Random(),
                  bot_user_id=0, bot_username="botucha_bot", sleep=_nosleep)
    t = time.time()
    await bot.bootstrap()
    q = store.conn.execute
    print(f"done in {time.time() - t:.0f}s: messages {q('SELECT COUNT(*) FROM messages').fetchone()[0]}, "
          f"chunks {q('SELECT COUNT(*) FROM chunks').fetchone()[0]}, facts {q('SELECT COUNT(*) FROM facts').fetchone()[0]}, "
          f"profiles {q('SELECT COUNT(*) FROM profiles').fetchone()[0]}")


def main() -> None:
    from .__main__ import load_env

    ap = argparse.ArgumentParser(prog="botucha.evaluation")
    ap.add_argument("mode", choices=["persona", "memory", "bootstrap"])
    ap.add_argument("--config", type=Path, default=Path("config.toml"))
    ap.add_argument("--model")
    ap.add_argument("--prompts", type=Path, default=Path("eval/prompts.toml"))
    a = ap.parse_args()
    cfg = load_config(a.config.resolve(), {**load_env(a.config.resolve().parent / ".env"), **os.environ})
    if a.model:
        cfg = dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, chat_model=a.model))
    spec = tomllib.loads(a.prompts.read_text())
    if a.mode == "bootstrap":
        asyncio.run(run_bootstrap(cfg))
    elif a.mode == "persona":
        print("wrote", asyncio.run(run_persona(cfg, spec["prompt"], Path("eval/out"))))
    else:
        asyncio.run(run_memory(cfg, spec["memory"]["queries"]))


if __name__ == "__main__":
    main()
