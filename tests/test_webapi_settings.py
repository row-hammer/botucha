"""Ratings review and export, bot controls, persona and config editing with validation and backups."""
import json
import os
import stat

from botucha.config import load_config
from botucha.store import StoredMessage
from botucha.trace import Tracer
from tests.test_app import C
from tests.webfix import web  # noqa: F401

BOT = 999


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def seed_ratings(store):
    store.upsert_member(111, "Tadas", "tadas")
    for i, (uid, name, text) in enumerate([(111, "Tadas", "ką daryt su nvidia?"), (BOT, "Botucha", "laikyk, žąsine")]):
        store.add_message(StoredMessage(C, 10 + i, uid, name, 9_000.0 + i, text, None, uid == BOT))
    store.set_feedback(C, 11, 111, -1, "per šiurkštu", 9_100.0)
    store.set_correction(C, 11, 111, "laikyk, bet neperk daugiau", 9_200.0)
    run = Tracer(store).start("reply", chat_id=C, msg_id=10)
    run.finish("sent", reply="laikyk, žąsine", sent=[(C, 11)])
    return run.id


async def test_ratings_list_review_and_export(web):
    client, deps, _ = await web()
    tid = seed_ratings(deps.store)
    rows = (await client.get("/api/ratings")).json()
    assert [r["kind"] for r in rows] == ["correction", "feedback"]
    fb = rows[1]
    assert fb["score"] == -1 and fb["reason"] == "per šiurkštu" and fb["original"] == "laikyk, žąsine"
    assert fb["user_name"] == "Tadas" and fb["trace_id"] == tid and fb["reviewed"] is False
    assert rows[0]["text"] == "laikyk, bet neperk daugiau"
    r = await client.post("/api/ratings/review", json={"kind": "feedback", "chat_id": C, "msg_id": 11,
                                                      "user_id": 111, "reviewed": True})
    assert r.status_code == 200
    assert (await client.get("/api/ratings")).json()[1]["reviewed"] is True
    missing = await client.post("/api/ratings/review", json={"kind": "feedback", "chat_id": C, "msg_id": 99,
                                                            "user_id": 111, "reviewed": True})
    assert missing.status_code == 404
    exp = await client.get("/api/ratings/export")
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    lines = [json.loads(line) for line in exp.text.splitlines()]
    assert len(lines) == 2 and "žąsine" in exp.text  # Lithuanian letters unescaped
    bad = next(x for x in lines if "score" in x)
    assert bad["history"] == ["Tadas: ką daryt su nvidia?"] and bad["reply"] == "laikyk, žąsine"
    assert next(x for x in lines if "correction" in x)["correction"] == "laikyk, bet neperk daugiau"


async def test_control_state_writes_state(web):
    client, deps, _ = await web()
    r = await client.post("/api/control/state", json={"enabled": False, "random_n": 9, "quiet_min": 5})
    assert r.status_code == 200 and r.json()["enabled"] is False
    g = deps.store.get_state
    assert (g("enabled"), g("random_n"), g("quiet_until")) == ("0", "9", str(10_000.0 + 300))
    assert (await client.post("/api/control/state", json={"random_n": 1})).status_code == 422
    assert (await client.post("/api/control/state", json={"quiet_min": -1})).status_code == 422
    await client.post("/api/control/state", json={"quiet_min": 0})
    assert g("quiet_until") == "0"


async def test_service_actions_and_journal(web):
    client, deps, _ = await web()
    assert (await client.post("/api/control/service", json={"action": "restart"})).status_code == 200
    assert deps.service.actions == ["restart"]
    assert (await client.post("/api/control/service", json={"action": "rm -rf"})).status_code == 422
    assert (await client.get("/api/control/journal?n=1")).json() == {"lines": ["INFO aiogram.dispatcher: Start polling"]}


async def test_persona_rejects_empty_and_huge(web):
    client, deps, _ = await web()
    before = deps.cfg.paths.persona.read_text()
    assert (await client.put("/api/persona", json={"text": "   \n"})).status_code == 422
    huge = "x" * (deps.cfg.model.num_ctx * 3 // 2 + 1)
    assert (await client.put("/api/persona", json={"text": huge})).status_code == 422
    assert deps.cfg.paths.persona.read_text() == before
    assert not deps.backups_dir.exists() or not any(deps.backups_dir.iterdir())


async def test_persona_save_backs_up(web):
    client, deps, _ = await web()
    old = deps.cfg.paths.persona.read_text()
    from botucha.webapi.routes_settings import persona_limit
    assert (await client.get("/api/persona")).json() == {"text": old, "limit": persona_limit(deps.cfg)}
    r = await client.put("/api/persona", json={"text": "tu esi botucha, naujas"})
    assert r.status_code == 200
    assert deps.cfg.paths.persona.read_text() == "tu esi botucha, naujas"
    [backup] = list(deps.backups_dir.iterdir())
    assert backup.name.startswith("persona-") and backup.read_text() == old
    assert mode(backup) == 0o600 and mode(deps.cfg.paths.persona) == 0o600


async def test_config_rejects_invalid(web):
    client, deps, _ = await web()
    before = deps.config_path.read_bytes()
    assert (await client.put("/api/config", json={"values": {"model.temperature": 5}})).status_code == 422
    assert (await client.put("/api/config", json={"values": {"telegram.admin_id": 1}})).status_code == 422
    assert (await client.put("/api/config", json={"values": {"trigger.keywords": "spx"}})).status_code == 422
    assert deps.config_path.read_bytes() == before


async def test_config_get_and_save_keeps_comments(web):
    client, deps, _ = await web()
    got = (await client.get("/api/config")).json()
    assert got["values"]["model.temperature"] == 0.7 and got["values"]["trigger.random_n"] == 25
    assert "telegram.admin_id" not in got["values"] and "token" not in json.dumps(got).lower()
    r = await client.put("/api/config", json={"values": {"model.temperature": 0.5, "trigger.keywords": ["spx", "btc"]}})
    assert r.status_code == 200 and r.json()["restart_required"] is True
    text = deps.config_path.read_text()
    assert "# Lower = fewer invented words" in text
    cfg = load_config(deps.config_path, {"BOTUCHA_TOKEN": "x"})
    assert cfg.model.temperature == 0.5 and cfg.trigger.keywords == ("spx", "btc")
    assert [b.name.startswith("config-") for b in deps.backups_dir.iterdir()] == [True]
    assert mode(deps.config_path) == 0o600


async def test_config_rejects_zero_that_would_silence_the_bot(web):
    client, deps, _ = await web()
    for key in ("trigger.user_calls_per_min", "trigger.reaction_n"):
        assert (await client.put("/api/config", json={"values": {key: 0}})).status_code == 422


async def test_config_get_fills_keys_missing_from_old_files(web):
    client, deps, _ = await web()
    text = deps.config_path.read_text()
    deps.config_path.write_text("\n".join(l for l in text.splitlines() if not l.startswith(("temperature", "user_calls_per_min"))))
    values = (await client.get("/api/config")).json()["values"]
    assert values["model.temperature"] == deps.cfg.model.temperature
    assert values["trigger.user_calls_per_min"] == deps.cfg.trigger.user_calls_per_min


async def test_config_min_p_editable_within_range(web):
    client, deps, _ = await web()
    assert (await client.put("/api/config", json={"values": {"model.min_p": 1.5}})).status_code == 422
    assert (await client.put("/api/config", json={"values": {"model.min_p": 0.1}})).status_code == 200
    assert load_config(deps.config_path, {"BOTUCHA_TOKEN": "x"}).model.min_p == 0.1
    assert (await client.get("/api/config")).json()["values"]["model.min_p"] == 0.1


async def test_saving_the_reply_frequency_also_sets_the_live_value(web):
    """/daznis and the Controls page store the live value in the state table, and it wins over the config at
    start. A frequency saved in Settings must not be silently ignored because of an older /daznis."""
    client, deps, _ = await web()
    deps.store.set_state("random_n", "40")
    r = await client.put("/api/config", json={"values": {"trigger.random_n": 10}})
    assert r.status_code == 200 and deps.store.get_state("random_n") == "10"
    assert (await client.get("/api/status")).json()["random_n"] == 10
    await client.put("/api/config", json={"values": {"model.temperature": 0.5}})
    assert deps.store.get_state("random_n") == "10"  # other saves leave it alone
