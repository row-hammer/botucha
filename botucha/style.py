"""Pick real group lines as style examples for the persona prompt."""
from __future__ import annotations

import sys
from pathlib import Path

from .chunking import render_line
from .store import StoredMessage


def select_examples(msgs: list[StoredMessage], n: int = 60, max_len: int = 150) -> list[str]:
    usable = [m for m in msgs if m.text.strip() and len(m.text) <= 200]
    step = max(1, len(usable) // n)
    return [f"{m.name}: {' '.join(m.text.split())[:max_len]}" for m in usable[::step][:n]]


def main(argv: list[str]) -> None:
    from .export_import import parse_export

    src, dst = Path(argv[0]), Path(argv[1])
    _, msgs = parse_export(src)
    lines = select_examples(msgs)
    dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} lines to {dst}")


if __name__ == "__main__":
    main(sys.argv[1:])
