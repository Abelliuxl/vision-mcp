# tests/test_config.py
import pytest
from vision_mcp.config import load_config, ConfigError


def _set_env(monkeypatch, **overrides):
    base = {
        "ARK_BASE_URL": "https://ark.cn-beijing.volces.com",
        "ARK_API_KEY": "test-key",
        "ARK_MODEL": "doubao-seed-2-0-mini-260215",
        "VISION_BEARER_TOKEN": "a" * 32,
        "HOST": "127.0.0.1",
        "PORT": "8100",
    }
    base.update(overrides)
    for k, v in base.items():
        monkeypatch.setenv(k, v)


def test_load_config_returns_dataclass(monkeypatch):
    _set_env(monkeypatch)
    cfg = load_config()
    assert cfg.ark_base_url == "https://ark.cn-beijing.volces.com"
    assert cfg.ark_api_key == "test-key"
    assert cfg.ark_model == "doubao-seed-2-0-mini-260215"
    assert cfg.vision_bearer_token == "a" * 32
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8100


def test_load_config_missing_key_raises(monkeypatch):
    _set_env(monkeypatch, ARK_API_KEY="")
    with pytest.raises(ConfigError, match="ARK_API_KEY"):
        load_config()


def test_load_config_missing_bearer_raises(monkeypatch):
    _set_env(monkeypatch, VISION_BEARER_TOKEN="")
    with pytest.raises(ConfigError, match="VISION_BEARER_TOKEN"):
        load_config()


def test_load_config_short_bearer_raises(monkeypatch):
    _set_env(monkeypatch, VISION_BEARER_TOKEN="short")
    with pytest.raises(ConfigError, match="at least 16"):
        load_config()


def test_load_config_invalid_port_raises(monkeypatch):
    _set_env(monkeypatch, PORT="not-a-number")
    with pytest.raises(ConfigError, match="PORT"):
        load_config()
