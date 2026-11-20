from pathlib import Path

import pytest

from botucha.config import ConfigError, load_config

EXAMPLE = Path(__file__).parent.parent / "config.example.toml"


def test_loads_example_config():
    cfg = load_config(EXAMPLE, {"BOTUCHA_TOKEN": "t"})
    assert cfg.trigger.random_n == 25
    assert cfg.trigger.cooldown_s == 180
    assert cfg.telegram.token == "t"
    assert cfg.model.num_predict == 150
    assert cfg.telegram.chat_ids == (-1001234567890,)
    assert "🤡" in cfg.trigger.reactions


def test_missing_token_raises():
    with pytest.raises(ConfigError):
        load_config(EXAMPLE, {})


def test_empty_chat_ids_raises(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(EXAMPLE.read_text().replace("chat_ids = [-1001234567890]", "chat_ids = []"))
    with pytest.raises(ConfigError):
        load_config(p, {"BOTUCHA_TOKEN": "t"})
