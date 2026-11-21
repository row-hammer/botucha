"""Chat model access via Ollama."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

import ollama

from .config import ModelCfg

TIMEOUT_S = 180  # a cold 31B load is slow; a hung Ollama must not block the worker forever


class LLM(Protocol):
    async def chat(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False) -> str: ...


@dataclass
class ChatResult:
    text: str
    stats: dict = field(default_factory=dict)


async def chat_ex(llm: Any, messages: list[dict], *, num_predict: int, fmt_json: bool = False,
                  images: list[bytes] | None = None) -> ChatResult:
    """Text plus model stats when the LLM can give them (Ollama), plain text otherwise.
    images go with the last user message; an LLM without chat_ex cannot see them."""
    if hasattr(llm, "chat_ex"):
        return await llm.chat_ex(messages, num_predict=num_predict, fmt_json=fmt_json, images=images)
    return ChatResult(await llm.chat(messages, num_predict=num_predict, fmt_json=fmt_json), {})


class OllamaLLM:
    def __init__(self, cfg: ModelCfg):
        self.cfg = cfg
        self.client = ollama.AsyncClient(host=cfg.ollama_host, timeout=TIMEOUT_S)

    @staticmethod
    def _stats(r: Mapping) -> dict:
        def ms(key: str) -> float:
            return float(r.get(key) or 0) / 1e6
        eval_ms = ms("eval_duration")
        count = int(r.get("eval_count") or 0)
        return {"model": r.get("model"), "prompt_eval_count": int(r.get("prompt_eval_count") or 0),
                "eval_count": count, "eval_ms": eval_ms, "prompt_eval_ms": ms("prompt_eval_duration"),
                "load_ms": ms("load_duration"), "total_ms": ms("total_duration"),
                "tok_s": count / (eval_ms / 1000) if eval_ms else None}

    async def chat(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False) -> str:
        return (await self.chat_ex(messages, num_predict=num_predict, fmt_json=fmt_json)).text

    async def has_vision(self) -> bool:
        try:
            return "vision" in ((await self.client.show(self.cfg.chat_model)).capabilities or [])
        except Exception:
            return False

    async def chat_ex(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False,
                      images: list[bytes] | None = None) -> ChatResult:
        if images:
            messages = [dict(m) for m in messages]
            last = max(i for i, m in enumerate(messages) if m.get("role") == "user")
            messages[last]["images"] = list(images)
        r = await self.client.chat(
            model=self.cfg.chat_model, messages=messages, think=False, keep_alive=self.cfg.keep_alive,
            format="json" if fmt_json else None,
            options={"num_ctx": self.cfg.num_ctx, "num_predict": num_predict,
                     "temperature": self.cfg.temperature})
        raw = r.model_dump() if hasattr(r, "model_dump") else dict(r)  # dict in tests
        return ChatResult(r["message"]["content"] or "", self._stats(raw))
