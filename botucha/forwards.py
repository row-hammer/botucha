"""Forwarded posts: stored as "[persiųsta iš <source>] <text>", so the model, learning and the spell check can
tell someone else's post (usually a news channel) from what the member who shared it wrote."""
from __future__ import annotations

import re

PREFIX = "[persiųsta iš "
MAX_SOURCE = 60
_MEDIA = r"(?:\[(?:nuotrauka|gif)(?::[^\]]*)?\] )?"
_TAGGED = re.compile(rf"^{_MEDIA}\[persiųsta iš ([^\]\n]*)\] ?")
# a transcript or chunk line "Name: [persiųsta iš …] …" (optionally after a photo or GIF tag)
FORWARD_LINE = re.compile(rf"^[^\n:]{{1,64}}: {_MEDIA}\[persiųsta iš ")


def _clean_source(name: str) -> str:
    """The source's name as data: no brackets or line breaks that could end the tag, and short."""
    name = " ".join(re.sub(r"[\[\]]", "", name or "").split())
    return (name[:MAX_SOURCE].rstrip() + "…") if len(name) > MAX_SOURCE else (name or "?")


def forward_text(source: str, text: str) -> str:
    text = text.strip()
    tag = f"{PREFIX}{_clean_source(source)}]"
    return f"{tag} {text}" if text else tag


def is_forwarded(text: str) -> bool:
    return _TAGGED.match(text) is not None


def forwarded_from(text: str) -> str | None:
    m = _TAGGED.match(text)
    return m.group(1) if m else None


def strip_forward(text: str) -> str:
    """The forwarded post without its tag (a photo or GIF tag in front is dropped too)."""
    return _TAGGED.sub("", text, count=1).strip()
