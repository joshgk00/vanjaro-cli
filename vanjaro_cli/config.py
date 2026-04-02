"""Configuration management — reads from ~/.vanjaro-cli/config.json and env vars."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, field_validator

__all__ = ["Config", "ConfigError", "load_config", "save_config", "clear_session", "CONFIG_DIR", "CONFIG_FILE"]

CONFIG_DIR = Path.home() / ".vanjaro-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config(BaseModel):
    base_url: str
    # Cookie-based auth: serialized cookie dict from requests session
    cookies: dict[str, str] | None = None
    portal_id: int = 0

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_authenticated(self) -> bool:
        return bool(self.cookies)


def load_config() -> Config:
    """Load config from file, falling back to env vars."""
    stored: dict = {}
    if CONFIG_FILE.exists():
        stored = json.loads(CONFIG_FILE.read_text())

    base_url = os.environ.get("VANJARO_BASE_URL", stored.get("base_url", ""))
    if not base_url:
        raise ConfigError(
            "No base URL configured. Run `vanjaro auth login --url <URL>` "
            "or set VANJARO_BASE_URL."
        )

    return Config(
        base_url=base_url,
        cookies=stored.get("cookies"),
        portal_id=int(os.environ.get("VANJARO_PORTAL_ID", stored.get("portal_id", 0))),
    )


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(config.model_dump_json(indent=2))
    CONFIG_FILE.chmod(0o600)


def clear_session() -> None:
    """Remove auth cookies while preserving base_url."""
    if not CONFIG_FILE.exists():
        return
    data = json.loads(CONFIG_FILE.read_text())
    data.pop("cookies", None)
    # Clean up legacy JWT fields if present
    data.pop("token", None)
    data.pop("refresh_token", None)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


class ConfigError(Exception):
    pass
