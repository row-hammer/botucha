"""Text embeddings via Ollama (bge-m3, forced onto CPU so the chat model keeps the GPU)."""
from __future__ import annotations

from typing import Protocol

import numpy as np
import ollama


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> np.ndarray: ...


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(n == 0, 1, n)


class OllamaEmbedder:
    def __init__(self, host: str, model: str = "bge-m3"):
        self.client = ollama.AsyncClient(host=host)
        self.model = model

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        r = await self.client.embed(model=self.model, input=texts, options={"num_gpu": 0})
        return normalize(np.array(r["embeddings"], dtype=np.float32))
