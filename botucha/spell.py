"""Catch invented Lithuanian words with hunspell (lt_LT from LibreOffice) plus the group's own vocabulary."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .trigger import fold

log = logging.getLogger(__name__)

_WORD = re.compile(r"[^\W\d_]+")  # letters only: vram'ą -> vram, ą; numbers and tickers' digits drop out


class Speller:
    def __init__(self, dict_base: Path, vocab: Callable[[], set[str]], *, vocab_ttl_s: float = 300):
        self.dict_base = Path(dict_base)
        self.vocab_fn, self.vocab_ttl_s = vocab, vocab_ttl_s
        self._vocab: set[str] = set()
        self._vocab_at = -1e18
        self.binary = shutil.which("hunspell")
        self.enabled = bool(self.binary) and self.dict_base.with_suffix(".dic").exists() \
            and self.dict_base.with_suffix(".aff").exists()
        if not self.enabled:
            log.warning("spell check disabled (hunspell or %s.dic/.aff missing)", self.dict_base)

    def _known(self) -> set[str]:
        now = time.monotonic()
        if now - self._vocab_at > self.vocab_ttl_s:
            self._vocab = {fold(w) for w in self.vocab_fn()}
            self._vocab_at = now
        return self._vocab

    def unknown(self, texts: list[str]) -> list[str]:
        """Words that are neither in the dictionary nor in the group's vocabulary, in order, unique."""
        if not self.enabled:
            return []
        known = self._known()
        cand: list[str] = []
        for t in texts:
            for w in _WORD.findall(t):
                if len(w) <= 2 or w.isupper() or fold(w) in known or w in cand:
                    continue
                cand.append(w)
        if not cand:
            return []
        try:
            r = subprocess.run([self.binary, "-d", str(self.dict_base), "-i", "utf-8", "-l"],
                               input="\n".join(cand), capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("hunspell failed: %s", e)
            return []
        bad = set(r.stdout.split())
        return [w for w in cand if w in bad]
