"""Put a database backup back.

  systemctl --user stop botucha botucha-web
  uv run python -m botucha.restore backups/daily/botucha-YYYY-MM-DD.db --config config.toml
  systemctl --user start botucha botucha-web

Copying a backup over botucha.db by hand is not safe: if a service still has the database open, or the bot
was killed, a write-ahead log (botucha.db-wal) is left behind and SQLite replays it onto the copied file. The
result passes an integrity check and silently mixes old and new rows. This command refuses while the database
is open elsewhere, keeps what was there in backups/, and leaves no stale log behind."""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import quote

IN_USE = ("the database is open in another process; stop both services first: "
          "systemctl --user stop botucha botucha-web")


class RestoreError(Exception):
    pass


def _integrity(path: Path) -> str:
    """integrity_check of a file read as it is on disk: no locks taken, no log or index files created."""
    conn = sqlite3.connect(f"file:{quote(str(path.resolve()))}?immutable=1", uri=True)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def _check_backup(path: Path) -> None:
    if not path.is_file():
        raise RestoreError(f"backup {path} not found")
    try:
        ok = _integrity(path)
    except sqlite3.DatabaseError as e:
        raise RestoreError(f"backup {path} is not a readable database: {e}") from e
    if ok != "ok":
        raise RestoreError(f"backup {path} failed its integrity check: {ok}")


def _fold_log(db: Path) -> bool:
    """Fold the write-ahead log into the current database, which only works when nobody else has it open.
    True = one clean file now; False = the file is damaged and is kept as it is."""
    try:
        conn = sqlite3.connect(db, timeout=0)
    except sqlite3.DatabaseError:
        return False
    try:
        mode = str(conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0]).lower()
    except sqlite3.OperationalError as e:
        if "locked" in str(e) or "busy" in str(e):
            raise RestoreError(IN_USE) from e
        return False
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()
    if mode == "wal":  # leaving WAL mode needs to be the only connection
        raise RestoreError(IN_USE)
    return True


def _set_aside(db: Path, clean: bool) -> Path:
    folder = db.parent / "backups"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = folder / f"botucha-before-restore-{stamp}.db"
    n = 1
    while target.exists():
        target = folder / f"botucha-before-restore-{stamp}-{n}.db"
        n += 1
    shutil.move(db, target)
    os.chmod(target, 0o600)
    if not clean:  # a damaged database keeps its log files next to it, under the new name
        for suffix in ("-wal", "-shm"):
            side = Path(f"{db}{suffix}")
            if side.exists():
                shutil.move(side, Path(f"{target}{suffix}"))
    return target


def restore(backup: Path, db: Path) -> Path | None:
    """Replace db with backup. Returns where the previous database was kept, or None if there was none."""
    backup, db = Path(backup), Path(db)
    _check_backup(backup)
    if db.exists() and backup.resolve() == db.resolve():
        raise RestoreError("the backup and the database are the same file")
    clean = _fold_log(db) if db.exists() else True
    tmp = db.with_name(f".{db.name}.restore.tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out, open(backup, "rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        if _integrity(tmp) != "ok":
            raise RestoreError(f"the copy of {backup} failed its integrity check")
        aside = _set_aside(db, clean) if db.exists() else None
        for suffix in ("-wal", "-shm"):  # a log from the old database must never meet the new file
            Path(f"{db}{suffix}").unlink(missing_ok=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, db)
    finally:
        tmp.unlink(missing_ok=True)
    return aside


def _db_from_config(config: Path) -> Path:
    try:
        raw = tomllib.loads(config.read_text())
        return config.parent / raw["paths"]["db"]
    except (OSError, tomllib.TOMLDecodeError, KeyError) as e:
        raise RestoreError(f"cannot find the database path in {config}: {e}") from e


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="botucha.restore", description="Put a database backup back.")
    p.add_argument("backup", type=Path)
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    p.add_argument("--db", type=Path, help="database file to replace (default: paths.db from the config)")
    a = p.parse_args(argv)
    try:
        db = a.db.resolve() if a.db else _db_from_config(a.config.resolve())
        aside = restore(a.backup, db)
    except RestoreError as e:
        print(f"not restored: {e}", file=sys.stderr)
        return 1
    print(f"restored {db} from {a.backup}")
    if aside:
        print(f"the previous database is kept as {aside}")
    print("now start the services: systemctl --user start botucha botucha-web")
    return 0


if __name__ == "__main__":
    sys.exit(main())
