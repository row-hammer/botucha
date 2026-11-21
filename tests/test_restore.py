"""Putting a backup back: the result is exactly the backup, never a mix with a leftover write-ahead log."""
import datetime as dt
import os
import shutil
import sqlite3
import stat

import pytest

from botucha.backup import daily_backup
from botucha.restore import RestoreError, main, restore
from botucha.store import Store

DAY = dt.date(2026, 11, 22)


def values(path):
    conn = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    try:
        return dict(conn.execute("SELECT key, value FROM state"))
    finally:
        conn.close()


def live_db_with_backup(folder):
    """A database with a backup taken, then written to again. Returns (db, backup, open store)."""
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "botucha.db"
    s = Store(db)
    for i in range(50):
        s.set_state(f"k{i}", "before")
    backup = daily_backup(s.conn, folder / "backups" / "daily", DAY)
    for i in range(100):
        s.set_state(f"k{i}", "after")
    return db, backup, s


def crashed_copy(db, s, folder):
    """The files a killed bot leaves behind: the database plus a write-ahead log nobody folded in."""
    folder.mkdir()
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(f"{db}{suffix}", folder / f"botucha.db{suffix}")
    s.conn.close()
    assert (folder / "botucha.db-wal").stat().st_size > 0
    return folder / "botucha.db"


def test_restore_with_a_leftover_wal_equals_the_backup(tmp_path):
    db, backup, s = live_db_with_backup(tmp_path / "live")
    crashed = crashed_copy(db, s, tmp_path / "crashed")

    aside = restore(backup, crashed)

    assert values(crashed) == values(backup) == {f"k{i}": "before" for i in range(50)}
    assert not (tmp_path / "crashed" / "botucha.db-wal").exists()
    assert not (tmp_path / "crashed" / "botucha.db-shm").exists()
    assert stat.S_IMODE(os.stat(crashed).st_mode) == 0o600
    # what was there before is kept whole, including the writes that were still in the log
    assert values(aside) == {f"k{i}": "after" for i in range(100)}
    assert aside.parent == tmp_path / "crashed" / "backups" and stat.S_IMODE(os.stat(aside).st_mode) == 0o600


def test_restore_refuses_while_another_process_has_the_database_open(tmp_path):
    db, backup, s = live_db_with_backup(tmp_path / "live")  # s plays the dashboard that was left running

    with pytest.raises(RestoreError, match="open"):
        restore(backup, db)

    assert s.get_state("k99") == "after"  # nothing was touched
    assert list((tmp_path / "live" / "backups").glob("botucha-before-restore-*")) == []


HOLDER = """
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("SELECT COUNT(*) FROM state").fetchone()
print("open", flush=True)
sys.stdin.read()  # idle, like a dashboard nobody is looking at
"""


def test_restore_refuses_while_a_separate_idle_process_has_it_open(tmp_path):
    import subprocess
    import sys
    db, backup, s = live_db_with_backup(tmp_path / "live")
    s.conn.close()
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, str(db)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              text=True)
    try:
        assert holder.stdout.readline().strip() == "open"
        with pytest.raises(RestoreError, match="open"):
            restore(backup, db)
        assert values(db)["k99"] == "after"
    finally:
        holder.stdin.close()
        holder.wait(timeout=5)
    restore(backup, db)  # once it is gone the same call goes through
    assert values(db) == values(backup)


def test_restore_rejects_a_file_that_is_not_a_healthy_database(tmp_path):
    db, backup, s = live_db_with_backup(tmp_path / "live")
    s.conn.close()
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database at all" * 100)

    with pytest.raises(RestoreError, match="backup"):
        restore(broken, db)
    with pytest.raises(RestoreError, match="backup"):
        restore(tmp_path / "missing.db", db)

    assert values(db)["k99"] == "after"


def test_restore_over_a_damaged_database_keeps_the_damaged_files(tmp_path):
    db, backup, s = live_db_with_backup(tmp_path / "live")
    s.conn.close()
    db.write_bytes(b"garbage" * 1000)

    aside = restore(backup, db)

    assert values(db) == values(backup)
    assert aside.read_bytes().startswith(b"garbage")


def test_restore_onto_a_machine_without_a_database(tmp_path):
    _, backup, s = live_db_with_backup(tmp_path / "live")
    s.conn.close()
    target = tmp_path / "new" / "botucha.db"
    target.parent.mkdir()

    assert restore(backup, target) is None
    assert values(target) == values(backup)


def test_command_line_reports_and_returns_an_exit_code(tmp_path, capsys):
    db, backup, s = live_db_with_backup(tmp_path / "live")
    assert main([str(backup), "--db", str(db)]) == 1  # still open
    assert "stop" in capsys.readouterr().err
    s.conn.close()
    assert main([str(backup), "--db", str(db)]) == 0
    assert "restored" in capsys.readouterr().out
    assert values(db) == values(backup)
