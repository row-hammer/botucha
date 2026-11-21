"""Every fact records the chat it came from (None = written on the dashboard or before this was recorded).
Nothing filters by it yet: it is there so memory can later be kept per chat without guessing."""
import json
import sqlite3

from botucha.learn import learn_once
from botucha.memory import Memory
from botucha.store import Store, StoredMessage
from tests.fakes import FakeEmbedder, FakeLLM
from tests.test_app import C, app, inc  # noqa: F401  (app is a fixture)
from tests.webfix import web  # noqa: F401  (web is a fixture)


def origin(store, text):
    return store.conn.execute("SELECT chat_id FROM facts WHERE text=?", (text,)).fetchone()[0]


async def test_isimink_and_slengas_record_their_chat(app):
    bot, store, _, _ = await app()
    await bot.on_message(inc("/isimink Tadas turi daug coreweave", msg_id=1))
    await bot.on_message(inc("/slengas zjbs = labai gerai", msg_id=2))
    assert origin(store, "Tadas turi daug coreweave") == C and origin(store, "zjbs = labai gerai") == C
    assert bot.memory.all_facts()[0].chat_id == C


async def test_learning_records_the_chat_it_read():
    s = Store(":memory:")
    mem = Memory(s, FakeEmbedder(), clock=lambda: 100_000.0)
    s.add_message(StoredMessage(C, 1, 111, "Tadas", 0.0, "perku nvidia"))
    await mem.index_new_chunks(C, force=True)
    raw = json.dumps({"facts": [{"about": None, "text": "Tadas perka nvidia"}],
                      "slang": [{"word": "zjbs", "meaning": "gerai"}]})
    await learn_once(mem, FakeLLM([raw]), C)
    assert origin(s, "Tadas perka nvidia") == C and origin(s, "zjbs = gerai") == C


async def test_an_update_from_another_chat_keeps_where_the_fact_came_from():
    s = Store(":memory:")
    mem = Memory(s, FakeEmbedder(), clock=lambda: 1.0)
    fid, _ = await mem.upsert_fact("fact", "tadas turi daug coreweave akciju ir jas laiko", 5, "auto", chat_id=C)
    await mem.upsert_fact("fact", "tadas turi daug coreweave akciju ir jas laiko nvidia", 5, "auto", chat_id=4242)
    assert s.conn.execute("SELECT chat_id FROM facts WHERE id=?", (fid,)).fetchone()[0] == C


async def test_dashboard_facts_have_no_chat_and_the_api_shows_it(web):
    client, deps, _ = await web()
    r = await client.post("/api/facts", json={"kind": "fact", "text": "Jonas kepa kukulius"})
    assert r.status_code == 200 and r.json()["chat_id"] is None


def test_an_older_database_gets_the_column_with_unknown_origins(tmp_path):
    db = tmp_path / "old.db"
    s = Store(db)
    s.conn.execute("INSERT INTO facts (kind, text, about, source, created, updated, emb) "
                   "VALUES ('fact', 'senas faktas', NULL, 'auto', 0, 0, x'00')")
    s.conn.commit()
    s.conn.execute("ALTER TABLE facts DROP COLUMN chat_id")  # as it was before this change
    s.conn.commit()
    s.conn.close()
    s2 = Store(db)
    assert s2.conn.execute("SELECT chat_id FROM facts").fetchall() == [(None,)]
    assert "chat_id" in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(facts)")}
