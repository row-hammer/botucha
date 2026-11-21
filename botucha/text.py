"""Text normalisation shared by matching code: case and Lithuanian letters never decide a match."""
from __future__ import annotations

import unicodedata


def strip_marks(text: str) -> str:
    """Remove diacritics (ą -> a, Š -> S) and keep the case. Safe for regex patterns: \\W stays \\W."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Lowercase and strip diacritics (ą -> a, š -> s)."""
    return strip_marks(text.lower())
