"""Persona and a safe subset of config.toml. Every save is validated first and backed up."""
from __future__ import annotations

from pathlib import Path

import tomlkit
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..config import ConfigError, load_config
from .files import backup, write_private

router = APIRouter()

# key -> (type, min, max); lists are lists of strings
EDITABLE: dict[str, tuple[type, float | None, float | None]] = {
    "model.temperature": (float, 0.0, 2.0),
    "model.min_p": (float, 0.0, 1.0),
    "model.num_predict": (int, 16, 2048),
    "trigger.keywords": (list, None, None),
    "trigger.keyword_prob": (float, 0.0, 1.0),
    "trigger.random_n": (int, 2, 10_000),
    "trigger.cooldown_s": (int, 0, 86_400),
    "trigger.reaction_n": (int, 1, 10_000),  # 1 in N: 0 would mean "react to everything"
    "trigger.tyla_default_min": (int, 0, 10_080),
    "trigger.user_calls_per_min": (int, 1, 1_000),  # 0 would ignore every mention
    "trigger.burst_quiet_s": (float, 0.1, 600.0),
    "trigger.burst_max_s": (float, 0.1, 3_600.0),
}


class PersonaIn(BaseModel):
    text: str


class ConfigIn(BaseModel):
    values: dict[str, object]


def persona_limit(cfg) -> int:
    return cfg.model.num_ctx * 3 // 2  # half of the prompt budget (num_ctx * 3 chars)


@router.get("/api/persona")
async def get_persona(request: Request) -> dict:
    path: Path = request.app.state.deps.cfg.paths.persona
    return {"text": path.read_text(encoding="utf-8") if path.exists() else "", "limit": persona_limit(request.app.state.deps.cfg)}


@router.put("/api/persona")
async def put_persona(request: Request, body: PersonaIn) -> dict:
    deps = request.app.state.deps
    if not body.text.strip():
        raise HTTPException(422, "persona is empty")
    if len(body.text) > persona_limit(deps.cfg):
        raise HTTPException(422, f"persona is too long, max {persona_limit(deps.cfg)} characters")
    path: Path = deps.cfg.paths.persona
    backup(deps, path, "persona", ".md")
    write_private(path, body.text)
    return {"ok": True}


def _check(key: str, value: object) -> object:
    if key not in EDITABLE:
        raise HTTPException(422, f"{key} cannot be changed here")
    kind, lo, hi = EDITABLE[key]
    if kind is list:
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise HTTPException(422, f"{key} must be a list of words")
        return [v.strip().lower() for v in value]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(422, f"{key} must be a number")
    if kind is int and float(value) != int(value):
        raise HTTPException(422, f"{key} must be a whole number")
    v = kind(value)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise HTTPException(422, f"{key} must be between {lo} and {hi}")
    return v


@router.get("/api/config")
async def get_config(request: Request) -> dict:
    """Current values. Keys an older config.toml lacks are filled with the defaults the bot uses."""
    cfg = request.app.state.deps.cfg
    values = {}
    for key in EDITABLE:
        section, name = key.split(".")
        v = getattr(getattr(cfg, section), name)
        values[key] = list(v) if isinstance(v, tuple) else v
    return {"values": values, "restart_required": True}


@router.put("/api/config")
async def put_config(request: Request, body: ConfigIn) -> dict:
    deps = request.app.state.deps
    checked = {k: _check(k, v) for k, v in body.values.items()}
    path: Path = deps.config_path
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    for key, value in checked.items():
        section, name = key.split(".")
        doc.setdefault(section, tomlkit.table())[name] = value
    text = tomlkit.dumps(doc)
    tmp = path.with_name(f".{path.name}.check")
    try:
        write_private(tmp, text)
        new_cfg = load_config(tmp, {"BOTUCHA_TOKEN": deps.cfg.telegram.token or "x"})
    except ConfigError as e:
        raise HTTPException(422, str(e)) from e
    finally:
        tmp.unlink(missing_ok=True)
    backup(deps, path, "config", ".toml")
    write_private(path, text)
    deps.cfg = new_cfg
    return {"ok": True, "restart_required": True}
