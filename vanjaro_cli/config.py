"""Configuration management — reads from ~/.vanjaro-cli/config.json and env vars."""

import json
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, field_validator

CONFIG_DIR = Path.home() / ".vanjaro-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config(BaseModel):
    base_url: str
    token: Optional[str] = None
    refresh_token: Optional[str] = None
    portal_id: int = 0

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


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
        token=os.environ.get("VANJARO_TOKEN", stored.get("token")),
        refresh_token=stored.get("refresh_token"),
        portal_id=int(os.environ.get("VANJARO_PORTAL_ID", stored.get("portal_id", 0))),
    )


def save_config(config: Config) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(config.model_dump_json(indent=2))
    CONFIG_FILE.chmod(0o600)


def clear_token() -> None:
    """Remove auth tokens while preserving base_url."""
    if not CONFIG_FILE.exists():
        return
    data = json.loads(CONFIG_FILE.read_text())
    data.pop("token", None)
    data.pop("refresh_token", None)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


class ConfigError(Exception):
    pass
