"""Persona and memory evaluation.

  uv run python -m botucha.evaluation persona --config config.toml [--model NAME] [--judge OLLAMA_MODEL]
      --judge scores every reply against persona.md after all replies are made (one model swap). Use a
      different model than the bot's, so it does not grade its own writing; while it runs, the live bot
      waits for its own model to load again, so run it when the group is quiet.
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
from .persona_checks import caricature_flags, judge, overused, repeated_phrases, summarize
from .spell import Speller
from .store import Store, StoredMessage

EVAL_USER, EVAL_NAME = 1, "eval"


def check_reply(texts: list[str], member_names: list[str], serious: bool = False) -> list[str]:
    if not texts:
        return ["empty"]
    problems = []
    if not serious and any(len(t.split()) > 15 for t in texts):
        problems.append("too long")
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

    async def leave(self, chat_id):
        pass


async def _nosleep(_):
    return None


def _copy(store: Store) -> Store:
    mem = Store(":memory:")
    store.conn.backup(mem.conn)
    return mem


def load_spec(path: Path) -> dict:
    """The prompts file plus its private twin (prompts.local.toml, git-ignored) when there is one: a local
    prompt replaces the public one of the same name, new ones go last, and local tables (the jargon stems)
    replace public ones. Prompts about your own persona belong in the local file, not the public repo."""
    spec = tomllib.loads(path.read_text(encoding="utf-8"))
    local = path.with_name(path.stem + ".local" + path.suffix)
    if not local.exists():
        return spec
    extra = tomllib.loads(local.read_text(encoding="utf-8"))
    prompts = {p["name"]: p for p in spec.get("prompt", [])}
    for p in extra.pop("prompt", []):
        prompts[p["name"]] = p
    return {**spec, **extra, "prompt": list(prompts.values())}


async def judge_results(judge_llm, persona: str, results: list[dict]) -> list[dict]:
    """Adds a judge verdict to every result. Run after all replies, so Ollama swaps models only once."""
    for r in results:
        r["verdict"] = await judge(judge_llm, persona, r["text"], r["replies"], r["rubric"],
                                   members=r.get("members", []))
        v = r["verdict"]
        print(f"judge {r['name']}: {v.error or f'{v.score}/5, OOC {len(v.ooc)}/{len(v.atoms)}'}", flush=True)
    return results


def render_report(model: str, results: list[dict], stems: list[str], judge_model: str | None) -> str:
    lines = [f"# Persona eval: {model} ({date.today()})" + (f", judge {judge_model}" if judge_model else ""), ""]
    rows = []
    for r in results:
        # a prompt that asks for jargon (what a word means, say it in Russian) is not a caricature
        problems = r["problems"] + ([] if r.get("jargon_ok") else
                                    caricature_flags(r["replies"], stems, serious=r["serious"]))
        r["all_problems"] = problems
        lines += [f"## {r['name']} ({r['category']})", f"> {r['text']}", "", *[f"    {s}" for s in r["replies"]], "",
                  f"*{r['secs']:.1f}s*" + (f" — **problems: {', '.join(problems)}**" if problems else ""), ""]
        v = r.get("verdict")
        if v is not None:
            lines.append(f"judge: {v.error}" if v.error else
                         f"judge: {v.score}/5 · OOC {len(v.ooc)}/{len(v.atoms)} — {v.feedback}")
            lines += [f"- ✗ „{a.text}“ — {a.why}" for a in v.ooc] + [""]
            rows.append({"category": r["category"], "score": v.score, "ooc": len(v.ooc), "atoms": len(v.atoms)})
    replies = {r["name"]: r["replies"] for r in results if not r["serious"]}
    lines += ["## Summary", ""]
    if rows:
        s = summarize(rows)
        cats = " · ".join(f"{c} {'–' if x is None else x}" for c, x in s["by_category"].items())
        lines += [f"- judge: {'–' if s['score'] is None else s['score']}/5 · OOC {s['ooc']}/{s['atoms']} statements"
                  f" · judge failed {s['judge_failed']}", f"- by category: {cats}"]
    flagged = [r for r in results if r["all_problems"]]
    lines.append(f"- prompts with problems: {len(flagged)}/{len(results)}"
                 + (" (" + ", ".join(r["name"] for r in flagged) + ")" if flagged else ""))
    rep = repeated_phrases(replies)
    lines.append("- repeated phrases: " + ("; ".join(f"„{p}“ ({', '.join(n)})" for p, n in rep) if rep else "none"))
    over = overused(replies, stems)
    lines.append("- overused jargon: " + (", ".join(f"{s} ×{c}" for s, c in over) if over else "none"))
    return "\n".join(lines) + "\n"


async def run_persona(cfg, prompts: list[dict], out_dir: Path, stems: list[str] | None = None,
                      judge_llm=None, judge_model: str | None = None) -> Path:
    base = Store(cfg.paths.db)
    chat_id = cfg.telegram.chat_ids[-1]
    embedder = OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model)
    llm = OllamaLLM(cfg.model)
    results = []
    for i, p in enumerate(prompts):
        store = _copy(base)
        out = CaptureOutbox()
        bot = Botucha(cfg, store, Memory(store, embedder), llm, out, rng=random.Random(i),
                      bot_user_id=0, bot_username="botucha_bot", sleep=_nosleep, started_at=0)
        bot.speller = Speller(Path(__file__).resolve().parent.parent / "data" / "hunspell" / "lt", vocab=bot.vocabulary)
        msg_id = 10**9
        store.add_message(StoredMessage(chat_id, msg_id, EVAL_USER, EVAL_NAME, time.time(), p["text"]))
        t = time.time()
        await bot.run_job([ReplyJob(chat_id, msg_id, direct=True, serious=bool(p.get("serious")), recall=False)])
        secs = time.time() - t
        problems = check_reply(out.sent, bot._member_names(), serious=bool(p.get("serious")))
        results.append({"name": p["name"], "text": p["text"], "replies": out.sent, "secs": secs, "problems": problems,
                        "category": p.get("category", "bendra"), "rubric": p.get("rubric", ""),
                        "serious": bool(p.get("serious")), "jargon_ok": bool(p.get("jargon_ok")),
                        "members": sorted(set(bot._member_names()))})
        print(f"{p['name']}: {problems or 'ok'} ({secs:.1f}s)", flush=True)
    if judge_llm is not None:
        await judge_results(judge_llm, cfg.paths.persona.read_text(encoding="utf-8"), results)
    report = render_report(cfg.model.chat_model, results, stems or [], judge_model)
    print(report.split("## Summary", 1)[1].strip(), flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{date.today()}-{cfg.model.chat_model.replace(':', '_')}.md"
    path.write_text(report, encoding="utf-8")
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
    ap.add_argument("--judge", help="local Ollama model that scores the replies against the persona")
    a = ap.parse_args()
    cfg = load_config(a.config.resolve(), {**load_env(a.config.resolve().parent / ".env"), **os.environ})
    if a.model:
        cfg = dataclasses.replace(cfg, model=dataclasses.replace(cfg.model, chat_model=a.model))
    spec = load_spec(a.prompts)
    if a.mode == "bootstrap":
        asyncio.run(run_bootstrap(cfg))
    elif a.mode == "persona":
        judge_llm = None
        if a.judge:  # deterministic and unloaded a minute after the last verdict, so the bot's model comes back
            judge_llm = OllamaLLM(dataclasses.replace(cfg.model, chat_model=a.judge, temperature=0.0, keep_alive="1m"))
        stems = spec.get("caricature", {}).get("stems", [])
        print("wrote", asyncio.run(run_persona(cfg, spec["prompt"], Path("eval/out"), stems, judge_llm, a.judge)))
    else:
        asyncio.run(run_memory(cfg, spec["memory"]["queries"]))


if __name__ == "__main__":
    main()
