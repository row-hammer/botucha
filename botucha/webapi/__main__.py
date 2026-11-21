"""Run the dashboard: python -m botucha.webapi --config config.toml [--port 8765]."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from ..__main__ import load_env
from ..config import load_config
from ..embed import OllamaEmbedder
from ..memory import Memory
from ..store import Store
from .app import Deps, create_app
from .service import SystemdService


def cli() -> None:
    p = argparse.ArgumentParser(prog="botucha.webapi")
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config_path = args.config.resolve()
    env = {**load_env(config_path.parent / ".env"), **os.environ}
    cfg = load_config(config_path, env)
    store = Store(cfg.paths.db)
    deps = Deps(cfg=cfg, config_path=config_path, store=store,
                memory=Memory(store, OllamaEmbedder(cfg.model.ollama_host, cfg.model.embed_model)),
                service=SystemdService(), static_dir=Path(__file__).resolve().parents[2] / "web" / "out",
                backups_dir=config_path.parent / "backups", claude_key=bool(env.get("ANTHROPIC_API_KEY", "").strip()))
    app = create_app(deps, dev=os.environ.get("BOTUCHA_WEB_DEV") == "1", port=args.port)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", timeout_graceful_shutdown=3)


if __name__ == "__main__":
    cli()
