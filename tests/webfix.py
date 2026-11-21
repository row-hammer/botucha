"""Shared fixture for web API tests: an app over an in-memory store with a fake systemd."""
from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from botucha.memory import Memory
from botucha.store import Store
from botucha.webapi.app import Deps, create_app
from tests.fakes import FakeEmbedder
from tests.test_app import ROOT, make_cfg

TOKEN = "test-token"
BASE = "http://127.0.0.1:8765"


class FakeService:
    def __init__(self):
        self.state = "active"
        self.actions: list[str] = []
        self.lines = ["Started Botucha Telegram bot.", "INFO aiogram.dispatcher: Start polling"]

    async def is_active(self) -> str:
        return self.state

    async def run(self, action: str) -> None:
        self.actions.append(action)

    async def journal(self, n: int = 50) -> list[str]:
        return self.lines[-n:]


@pytest.fixture
async def web(tmp_path):
    clients = []

    async def factory(*, static_dir: Path | None = None, embedder=None, clock=lambda: 10_000.0):
        cfg = make_cfg(tmp_path)
        config_path = tmp_path / "config.toml"
        shutil.copy(ROOT / "config.example.toml", config_path)
        store = Store(":memory:")
        mem = Memory(store, embedder or FakeEmbedder(), clock=clock)
        deps = Deps(cfg=cfg, config_path=config_path, store=store, memory=mem, service=FakeService(),
                    static_dir=static_dir, clock=clock, backups_dir=tmp_path / "backups")
        app = create_app(deps, token=TOKEN)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE,
                                   headers={"X-Botucha-Token": TOKEN})
        clients.append(client)
        return client, deps, app

    yield factory
    for c in clients:
        await c.aclose()
