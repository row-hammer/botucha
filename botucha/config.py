"""Load config.toml plus the bot token from the environment."""
from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class TelegramCfg:
    token: str
    chat_ids: tuple[int, ...]
    admin_id: int
    bot_name_regex: str


@dataclass(frozen=True)
class ModelCfg:
    chat_model: str
    embed_model: str
    num_ctx: int
    num_predict: int
    keep_alive: str
    ollama_host: str
    temperature: float = 0.7
    min_p: float = 0.0


@dataclass(frozen=True)
class TriggerCfg:
    keywords: tuple[str, ...]
    keyword_prob: float
    random_n: int
    cooldown_s: int
    reaction_n: int
    reactions: tuple[str, ...]
    burst_quiet_s: float
    burst_max_s: float
    tyla_default_min: int
    user_calls_per_min: int = 5


@dataclass(frozen=True)
class PathsCfg:
    db: Path
    persona: Path
    style_examples: Path
    export: Path | None


@dataclass(frozen=True)
class MemoryCfg:
    locked_members: tuple[int, ...] = ()  # no automatic facts or profile refresh for these user IDs


@dataclass(frozen=True)
class PricesCfg:
    enabled: bool = True
    aliases: tuple[tuple[str, str], ...] = ()  # extra/overriding stem -> Yahoo symbol


@dataclass(frozen=True)
class Config:
    telegram: TelegramCfg
    model: ModelCfg
    trigger: TriggerCfg
    paths: PathsCfg
    memory: MemoryCfg = MemoryCfg()
    prices: PricesCfg = PricesCfg()


def load_config(path: Path, env: Mapping[str, str]) -> Config:
    try:
        raw = tomllib.loads(Path(path).read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    token = env.get("BOTUCHA_TOKEN", "").strip()
    if not token:
        raise ConfigError("BOTUCHA_TOKEN is not set")
    try:
        t, m, tr, p = raw["telegram"], raw["model"], raw["trigger"], raw["paths"]
        chat_ids = tuple(int(c) for c in t["chat_ids"])
        if not chat_ids:
            raise ConfigError("telegram.chat_ids is empty")
        base = Path(path).parent
        export = p.get("export")
        return Config(
            telegram=TelegramCfg(token, chat_ids, int(t["admin_id"]), str(t["bot_name_regex"])),
            model=ModelCfg(str(m["chat_model"]), str(m["embed_model"]), int(m["num_ctx"]),
                           int(m["num_predict"]), str(m["keep_alive"]), str(m["ollama_host"]),
                           float(m.get("temperature", 0.7)), float(m.get("min_p", ModelCfg.min_p))),
            trigger=TriggerCfg(tuple(str(k).lower() for k in tr["keywords"]), float(tr["keyword_prob"]),
                               int(tr["random_n"]), int(tr["cooldown_s"]), int(tr["reaction_n"]),
                               tuple(tr["reactions"]), float(tr["burst_quiet_s"]),
                               float(tr["burst_max_s"]), int(tr["tyla_default_min"]),
                               int(tr.get("user_calls_per_min", 5))),
            paths=PathsCfg(base / p["db"], base / p["persona"], base / p["style_examples"],
                           Path(export) if export else None),
            memory=MemoryCfg(tuple(int(u) for u in raw.get("memory", {}).get("locked_members", []))),
            prices=PricesCfg(bool(raw.get("prices", {}).get("enabled", True)),
                             tuple((str(k).lower(), str(v)) for k, v in raw.get("prices", {}).get("aliases", {}).items())),
        )
    except KeyError as e:
        raise ConfigError(f"missing config key: {e}") from e
