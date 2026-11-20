"""Chat model access via Ollama."""
from __future__ import annotations

from typing import Protocol

import ollama

from .config import ModelCfg

TIMEOUT_S = 180  # a cold 31B load is slow; a hung Ollama must not block the worker forever


class LLM(Protocol):
    async def chat(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False) -> str: ...


class OllamaLLM:
    def __init__(self, cfg: ModelCfg):
        self.cfg = cfg
        self.client = ollama.AsyncClient(host=cfg.ollama_host, timeout=TIMEOUT_S)

    async def chat(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False) -> str:
        r = await self.client.chat(
            model=self.cfg.chat_model, messages=messages, think=False, keep_alive=self.cfg.keep_alive,
            format="json" if fmt_json else None,
            options={"num_ctx": self.cfg.num_ctx, "num_predict": num_predict})
        return r["message"]["content"] or ""
