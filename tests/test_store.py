from botucha.store import Store, StoredMessage

C = -100


def msg(i, text="x", user=1, ts=None):
    return StoredMessage(chat_id=C, msg_id=i, user_id=user, name=f"u{user}", ts=ts or float(i), text=text)


def test_add_and_recent_order():
    s = Store(":memory:")
    for i in (1, 2, 3):
        s.add_message(msg(i, f"m{i}"))
    assert [m.text for m in s.recent_messages(C, 2)] == ["m2", "m3"]


def test_duplicate_message_ignored():
    s = Store(":memory:")
    assert s.add_message(msg(1)) is True
    assert s.add_message(msg(1)) is False
    assert len(s.recent_messages(C, 10)) == 1


def test_update_text():
    s = Store(":memory:")
    s.add_message(msg(1, "old"))
    s.update_message_text(C, 1, "new")
    assert s.recent_messages(C, 1)[0].text == "new"


def test_state_roundtrip():
    s = Store(":memory:")
    assert s.get_state("k", "d") == "d"
    s.set_state("k", "v")
    s.set_state("k", "v2")
    assert s.get_state("k") == "v2"


def test_member_upsert_updates_name():
    s = Store(":memory:")
    s.upsert_member(5, "Old", None)
    s.upsert_member(5, "New", "newnick")
    m = s.members()[5]
    assert (m.name, m.username) == ("New", "newnick")


def test_messages_after_and_last_rowid():
    s = Store(":memory:")
    s.add_message(msg(1))
    r = s.last_rowid(C)
    s.add_message(msg(2, "later"))
    after = s.messages_after(C, r)
    assert [m.text for _, m in after] == ["later"]
    assert s.last_rowid(C) == after[-1][0]


OLD_SCHEMA = ("CREATE TABLE messages (rowid INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL, msg_id INTEGER NOT NULL, "
              "user_id INTEGER NOT NULL, name TEXT NOT NULL, ts REAL NOT NULL, text TEXT NOT NULL, reply_to INTEGER, "
              "is_bot INTEGER NOT NULL DEFAULT 0, UNIQUE (chat_id, msg_id));")


def old_db(path):
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(OLD_SCHEMA)
    c.close()


def test_a_migration_holds_the_write_lock_from_check_to_change(tmp_path):
    """The bot and the dashboard can start at the same moment: both used to see a column missing and both
    added it, and the second died with 'duplicate column name'."""
    import sqlite3
    db = tmp_path / "old.db"
    old_db(db)
    seen = []

    class Probe(Store):
        def _migrate(self):
            other = sqlite3.connect(db, timeout=0)
            try:
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
                seen.append("other process could write")
            except sqlite3.OperationalError:
                seen.append("locked")
            finally:
                other.close()
            super()._migrate()
    Probe(db)
    assert seen == ["locked"]


def test_many_processes_starting_on_an_old_database_all_come_up(tmp_path):
    import subprocess
    import sys
    db = tmp_path / "old.db"
    old_db(db)
    code = "import sys; from botucha.store import Store; Store(sys.argv[1]); print('ok')"
    procs = [subprocess.Popen([sys.executable, "-c", code, str(db)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) for _ in range(6)]
    results = [p.communicate(timeout=30) for p in procs]
    assert [out.strip() for out, _ in results] == ["ok"] * 6, [err for _, err in results if err]
