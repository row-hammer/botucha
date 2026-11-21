"""Daily database backups: one per day, verified, private, last 7 kept."""
import datetime as dt
import os
import sqlite3
import stat

from botucha.backup import daily_backup
from botucha.store import Store, StoredMessage

DAY = dt.date(2026, 11, 22)


def store_with_data():
    s = Store(":memory:")
    s.add_message(StoredMessage(-1, 1, 5, "Tadas", 0.0, "labas"))
    return s


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_backup_is_a_working_copy(tmp_path):
    out = daily_backup(store_with_data().conn, tmp_path / "daily", DAY)
    assert out.name == "botucha-2026-11-22.db"
    copy = sqlite3.connect(out)
    assert copy.execute("SELECT text FROM messages").fetchone() == ("labas",)
    assert mode(out) == 0o600 and mode(tmp_path / "daily") == 0o700
    assert [p.name for p in (tmp_path / "daily").iterdir()] == ["botucha-2026-11-22.db"]  # no temp file left


def test_only_one_backup_per_day(tmp_path):
    s = store_with_data()
    assert daily_backup(s.conn, tmp_path, DAY) is not None
    assert daily_backup(s.conn, tmp_path, DAY) is None


def test_keeps_last_seven_and_leaves_other_files(tmp_path):
    s = store_with_data()
    (tmp_path / "botucha-2026-11-21-before-cleanup.db").write_text("manual")
    for i in range(10):
        daily_backup(s.conn, tmp_path, DAY + dt.timedelta(days=i))
    daily = sorted(p.name for p in tmp_path.glob("botucha-????-??-??.db"))
    assert len(daily) == 7 and daily[0] == "botucha-2026-11-25.db" and daily[-1] == "botucha-2026-12-01.db"
    assert (tmp_path / "botucha-2026-11-21-before-cleanup.db").read_text() == "manual"


async def test_bot_backup_failure_does_not_stop_it(tmp_path, monkeypatch):
    import botucha.app as appmod

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(appmod, "daily_backup", boom)
    from tests.test_app import BOT_ID, FakeOutbox, make_cfg, nosleep
    from botucha.app import Botucha
    from botucha.memory import Memory
    from tests.fakes import FakeEmbedder, FakeLLM
    import random
    store = Store(":memory:")
    bot = Botucha(make_cfg(tmp_path), store, Memory(store, FakeEmbedder()), FakeLLM([]), FakeOutbox(),
                  rng=random.Random(0), clock=lambda: 1_795_300_000.0, bot_user_id=BOT_ID, bot_username="b",
                  sleep=nosleep, started_at=0.0)
    bot.maintenance_tick()
    assert "disk full" in bot.last_error


async def test_bot_writes_backup_next_to_db(tmp_path):
    from tests.test_app import BOT_ID, FakeOutbox, make_cfg, nosleep
    from botucha.app import Botucha
    from botucha.memory import Memory
    from tests.fakes import FakeEmbedder, FakeLLM
    import dataclasses
    import random
    cfg = make_cfg(tmp_path)
    cfg = dataclasses.replace(cfg, paths=dataclasses.replace(cfg.paths, db=tmp_path / "botucha.db"))
    store = Store(cfg.paths.db)
    bot = Botucha(cfg, store, Memory(store, FakeEmbedder()), FakeLLM([]), FakeOutbox(), rng=random.Random(0),
                  clock=lambda: 1_795_300_000.0, bot_user_id=BOT_ID, bot_username="b", sleep=nosleep, started_at=0.0)
    bot.maintenance_tick()
    assert len(list((tmp_path / "backups" / "daily").glob("botucha-*.db"))) == 1
