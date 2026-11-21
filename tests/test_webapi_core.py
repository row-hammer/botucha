"""Web API core: session, status, host and token checks, busy database, missing UI build."""
import sqlite3

import httpx

from tests.webfix import BASE, TOKEN, web  # noqa: F401  (web is a fixture)


async def test_session_and_status(web):
    client, deps, _ = await web()
    deps.store.set_state("last_error", "send: boom")
    assert (await client.get("/api/session")).json() == {"token": TOKEN}
    st = (await client.get("/api/status")).json()
    assert st["bot"] == "active" and st["enabled"] is True and st["random_n"] == 25
    assert st["model"] == deps.cfg.model.chat_model and st["last_error"] == "send: boom"


async def test_status_when_bot_stopped(web):
    client, deps, _ = await web()
    deps.service.state = "failed"
    assert (await client.get("/api/status")).json()["bot"] == "failed"
    assert (await client.get("/api/session")).status_code == 200


async def test_bad_host_rejected(web):
    client, _, _ = await web()
    r = await client.get("/api/status", headers={"Host": "evil.example:8765"})
    assert r.status_code == 400 and r.json() == {"error": "bad host"}


async def test_post_without_token_forbidden(web):
    _, _, app = await web()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as anon:
        r = await anon.post("/api/control/state", json={})
        assert r.status_code == 403 and r.json() == {"error": "bad token"}
        r = await anon.post("/api/control/state", json={}, headers={"X-Botucha-Token": TOKEN})
        assert r.status_code != 403


async def test_locked_db_returns_503(web):
    client, _, app = await web()

    async def boom():
        raise sqlite3.OperationalError("database is locked")
    app.add_api_route("/api/test-locked", boom)
    r = await client.get("/api/test-locked")
    assert r.status_code == 503 and r.json() == {"error": "busy"}


async def test_root_without_build(web):
    client, _, _ = await web(static_dir=None)
    r = await client.get("/")
    assert r.status_code == 200 and "UI not built" in r.text


async def test_root_serves_build(web, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "index.html").write_text("<html>botucha ui</html>")
    client, _, _ = await web(static_dir=out)
    assert "botucha ui" in (await client.get("/")).text
