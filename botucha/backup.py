"""Daily copy of the database: SQLite online backup, verified, private, the last few kept."""
from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from pathlib import Path

NAME = re.compile(r"^botucha-(\d{4}-\d{2}-\d{2})\.db$")


def daily_backup(conn: sqlite3.Connection, folder: Path, today: dt.date, *, keep: int = 7) -> Path | None:
    """Write folder/botucha-<today>.db unless it exists. Returns the new file, or None if already done.
    Only files named exactly like daily backups are ever deleted."""
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    target = folder / f"botucha-{today.isoformat()}.db"
    if target.exists():
        return None
    tmp = folder / f".{target.name}.tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.close(fd)
        dest = sqlite3.connect(tmp)
        try:
            conn.backup(dest)  # consistent snapshot even while the bot and the web service write
            ok = dest.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dest.close()
        if ok != "ok":
            raise sqlite3.DatabaseError(f"backup failed integrity check: {ok}")
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    daily = sorted(p for p in folder.iterdir() if NAME.match(p.name))
    for old in daily[:-keep]:
        old.unlink()
    return target
