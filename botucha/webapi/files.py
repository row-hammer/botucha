"""Private file writes: atomic replace, mode 600, timestamped backups."""
from __future__ import annotations

import os
import time
from pathlib import Path


def backups_dir(deps) -> Path:
    d = Path(deps.backups_dir or deps.config_path.parent / "backups")
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


def write_private(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def backup(deps, path: Path, prefix: str, suffix: str) -> Path | None:
    if not path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(deps.clock()))
    target = backups_dir(deps) / f"{prefix}-{stamp}{suffix}"
    n = 1
    while target.exists():
        target = target.with_name(f"{prefix}-{stamp}-{n}{suffix}")
        n += 1
    write_private(target, path.read_text(encoding="utf-8"))
    return target
