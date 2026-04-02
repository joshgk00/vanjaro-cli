"""Configuration management — profiles, API keys, and env var overrides.

Supports named profiles for managing multiple Vanjaro/DNN sites.
Backward-compatible with the old flat config format (auto-migrates to a "default" profile).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, field_validator

__all__ = [
    "Config",
    "ConfigError",
    "derive_profile_name",
    "load_config",
    "save_config",
    "clear_session",
    "get_active_profile_name",
    "set_profile_override",
    "CONFIG_DIR",
    "CONFIG_FILE",
]

CONFIG_DIR = Path.home() / ".vanjaro-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Module-level override set by --profile flag
_profile_override: str | None = None


def derive_profile_name(base_url: str) -> str:
    """Derive a profile name from a URL's hostname (e.g., 'http://vanjarocli.local' -> 'vanjarocli-local')."""
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    hostname = parsed.hostname or base_url
    # Replace dots with dashes for a clean profile name
    return hostname.replace(".", "-")


class Config(BaseModel):
    """A single site profile."""

    base_url: str
    cookies: dict[str, str] | None = None
    api_key: str | None = None
    portal_id: int = 0

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_authenticated(self) -> bool:
        return bool(self.cookies)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def set_profile_override(name: str | None) -> None:
    """Set a profile override for the current CLI invocation (via --profile flag)."""
    global _profile_override
    _profile_override = name


def get_active_profile_name() -> str:
    """Return the active profile name, considering overrides."""
    if _profile_override:
        return _profile_override
    raw = _read_raw_config()
    return raw.get("active_profile", "default")


def load_config(profile_name: str | None = None) -> Config:
    """Load config for the given profile, falling back to env vars.

    Resolution order:
    1. Explicit profile_name argument
    2. Module-level _profile_override (set by --profile CLI flag)
    3. active_profile from config file
    4. "default"
    """
    raw = _read_raw_config()
    resolved_name = profile_name or _profile_override or raw.get("active_profile", "default")

    # Handle old flat format (no "profiles" key) — treat as "default" profile
    if "profiles" not in raw and "base_url" in raw:
        profile_data = raw
    else:
        profiles = raw.get("profiles", {})
        profile_data = profiles.get(resolved_name, {})

    base_url = os.environ.get("VANJARO_BASE_URL", profile_data.get("base_url", ""))
    if not base_url:
        if resolved_name != "default":
            raise ConfigError(f"Profile '{resolved_name}' not found.")
        raise ConfigError(
            "No base URL configured. Run `vanjaro auth login --url <URL>` "
            "or set VANJARO_BASE_URL."
        )

    return Config(
        base_url=base_url,
        cookies=profile_data.get("cookies"),
        api_key=profile_data.get("api_key"),
        portal_id=int(os.environ.get("VANJARO_PORTAL_ID", profile_data.get("portal_id", 0))),
    )


def save_config(config: Config, profile_name: str | None = None) -> None:
    """Save config under the given profile name."""
    resolved_name = profile_name or _profile_override or "default"
    raw = _read_raw_config()

    # Migrate old flat format to profiles format
    if "profiles" not in raw:
        if "base_url" in raw:
            raw = {
                "active_profile": "default",
                "profiles": {"default": {k: v for k, v in raw.items()}},
            }
        else:
            raw = {"active_profile": resolved_name, "profiles": {}}

    raw.setdefault("profiles", {})
    raw["profiles"][resolved_name] = config.model_dump()

    # Set as active if it's the first profile or if no active profile is set
    if "active_profile" not in raw or not raw["active_profile"]:
        raw["active_profile"] = resolved_name

    # When saving from login (cookies present), switch to this profile
    if config.cookies:
        raw["active_profile"] = resolved_name

    _write_raw_config(raw)


def set_active_profile(name: str) -> None:
    """Set the active profile in the config file."""
    raw = _read_raw_config()
    profiles = raw.get("profiles", {})
    if name not in profiles:
        raise ConfigError(f"Profile '{name}' does not exist.")
    raw["active_profile"] = name
    _write_raw_config(raw)


def delete_profile(name: str) -> None:
    """Remove a profile from the config file."""
    raw = _read_raw_config()
    profiles = raw.get("profiles", {})
    if name not in profiles:
        raise ConfigError(f"Profile '{name}' does not exist.")
    del profiles[name]

    # If we deleted the active profile, switch to another or clear
    if raw.get("active_profile") == name:
        raw["active_profile"] = next(iter(profiles), "")

    _write_raw_config(raw)


def list_profiles() -> list[dict[str, str]]:
    """Return a list of profile summaries."""
    raw = _read_raw_config()

    # Handle old flat format
    if "profiles" not in raw and "base_url" in raw:
        return [{"name": "default", "base_url": raw["base_url"], "active": True}]

    active = raw.get("active_profile", "default")
    profiles = raw.get("profiles", {})
    return [
        {
            "name": name,
            "base_url": data.get("base_url", ""),
            "active": name == active,
        }
        for name, data in profiles.items()
    ]


def clear_session(profile_name: str | None = None) -> None:
    """Remove auth cookies while preserving other profile settings."""
    resolved_name = profile_name or _profile_override or "default"
    raw = _read_raw_config()

    # Handle old flat format
    if "profiles" not in raw and "base_url" in raw:
        raw.pop("cookies", None)
        raw.pop("token", None)
        raw.pop("refresh_token", None)
        _write_raw_config(raw)
        return

    profiles = raw.get("profiles", {})
    if resolved_name in profiles:
        profiles[resolved_name].pop("cookies", None)
        _write_raw_config(raw)


def save_api_key(api_key: str, profile_name: str | None = None) -> None:
    """Store an API key in the given profile."""
    resolved_name = profile_name or _profile_override or get_active_profile_name()
    config = load_config(resolved_name)
    config.api_key = api_key
    save_config(config, resolved_name)


def remove_api_key(profile_name: str | None = None) -> None:
    """Remove the API key from the given profile."""
    resolved_name = profile_name or _profile_override or get_active_profile_name()
    config = load_config(resolved_name)
    config.api_key = None
    save_config(config, resolved_name)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _read_raw_config() -> dict:
    """Read the raw config file as a dict."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_raw_config(data: dict) -> None:
    """Write the raw config dict to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
    try:
        CONFIG_FILE.chmod(0o600)
    except OSError:
        pass  # chmod may fail on Windows


class ConfigError(Exception):
    pass
