"""Test doubles for Ollama-backed components."""
from __future__ import annotations

import re
import zlib

import numpy as np

from botucha.llm import ChatResult


class FakeEmbedder:
    """Deterministic bag-of-words hashing: texts sharing words get high cosine."""

    dim = 256

    def __init__(self):
        self.calls = 0

    async def embed(self, texts: list[str]) -> np.ndarray:
        self.calls += 1
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"\w+", t.lower()):
                out[i, zlib.crc32(w.encode()) % self.dim] += 1.0
            n = np.linalg.norm(out[i])
            if n:
                out[i] /= n
        return out


class FakeLLM:
    """Returns queued responses in order; an Exception item is raised instead."""

    def __init__(self, responses: list):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False) -> str:
        self.calls.append({"messages": messages, "num_predict": num_predict, "fmt_json": fmt_json})
        r = self.responses.pop(0) if self.responses else ""
        if isinstance(r, Exception):
            raise r
        return r

    async def chat_ex(self, messages: list[dict], *, num_predict: int, fmt_json: bool = False,
                      images: list[bytes] | None = None) -> ChatResult:
        self.calls.append({"messages": messages, "num_predict": num_predict, "fmt_json": fmt_json, "images": images})
        r = self.responses.pop(0) if self.responses else ""
        if isinstance(r, Exception):
            raise r
        text = r
        n = len(text.split())
        return ChatResult(text, {"model": "fake", "eval_count": n, "eval_ms": 10.0, "tok_s": n / 0.01})
