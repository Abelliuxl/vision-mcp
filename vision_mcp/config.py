"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when one or more required environment variables are missing or invalid."""


@dataclass(frozen=True)
class Config:
    ark_base_url: str
    ark_api_key: str
    ark_model: str
    vision_bearer_token: str
    host: str
    port: int


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required but not set")
    return value


def load_config() -> Config:
    bearer = _required("VISION_BEARER_TOKEN")
    if len(bearer) < 16:
        raise ConfigError("VISION_BEARER_TOKEN must be at least 16 characters")

    port_raw = _required("PORT")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ConfigError(f"PORT must be an integer, got {port_raw!r}") from exc

    return Config(
        ark_base_url=_required("ARK_BASE_URL").rstrip("/"),
        ark_api_key=_required("ARK_API_KEY"),
        ark_model=_required("ARK_MODEL"),
        vision_bearer_token=bearer,
        host=_required("HOST"),
        port=port,
    )
