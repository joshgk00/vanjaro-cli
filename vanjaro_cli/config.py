"""Configuration management — profiles, API keys, and env var overrides.

Supports named profiles for managing multiple Vanjaro/DNN sites.
Backward-compatible with the old flat config format (auto-migrates to a "default" profile).
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Iterator

from pydantic import BaseModel, field_validator

__all__ = [
    "Config",
    "ConfigError",
    "derive_profile_name",
    "get_profile_data",
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
    """Derive a profile name from a URL hostname."""
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

    base_url = profile_data.get("base_url") or os.environ.get("VANJARO_BASE_URL", "")
    if not base_url:
        if resolved_name != "default":
            raise ConfigError(f"Profile '{resolved_name}' not found.")
        raise ConfigError(
            "No base URL configured. Run `vanjaro auth login --url <URL>` "
            "or set VANJARO_BASE_URL."
        )

    portal_id = profile_data.get("portal_id")
    if portal_id is None:
        portal_id = os.environ.get("VANJARO_PORTAL_ID", 0)

    return Config(
        base_url=base_url,
        cookies=profile_data.get("cookies"),
        api_key=profile_data.get("api_key"),
        portal_id=int(portal_id),
    )


def get_profile_data(profile_name: str) -> dict:
    """Return the raw stored profile dict, or an empty dict if missing."""
    raw = _read_raw_config()
    return raw.get("profiles", {}).get(profile_name, {})


def save_config(
    config: Config,
    profile_name: str | None = None,
    *,
    preserve_active_profile: bool = False,
    replace_existing: bool = True,
) -> None:
    """Save a profile through a locked read-modify-replace operation."""
    resolved_name = profile_name or _profile_override or "default"
    with _config_lock():
        raw = _read_raw_config()

        # Migrate old flat format to profiles format.
        if "profiles" not in raw:
            if "base_url" in raw:
                raw = {
                    "active_profile": "default",
                    "profiles": {"default": {k: v for k, v in raw.items()}},
                }
            else:
                raw = {"active_profile": resolved_name, "profiles": {}}

        raw.setdefault("profiles", {})
        if resolved_name in raw["profiles"] and not replace_existing:
            raise ConfigError(
                f"Profile '{resolved_name}' was created after preview; "
                "it was not replaced."
            )
        raw["profiles"][resolved_name] = config.model_dump()

        # Set as active if it's the first profile or if no active profile is set.
        if "active_profile" not in raw or not raw["active_profile"]:
            raw["active_profile"] = resolved_name

        # When saving from login (cookies present), switch to this profile.
        if config.cookies and not preserve_active_profile:
            raw["active_profile"] = resolved_name

        _write_raw_config(raw)


def set_active_profile(name: str) -> None:
    """Set the active profile in the config file."""
    with _config_lock():
        raw = _read_raw_config()
        profiles = raw.get("profiles", {})
        if name not in profiles:
            raise ConfigError(f"Profile '{name}' does not exist.")
        raw["active_profile"] = name
        _write_raw_config(raw)


def delete_profile(name: str) -> None:
    """Remove a profile from the config file."""
    with _config_lock():
        raw = _read_raw_config()
        profiles = raw.get("profiles", {})
        if name not in profiles:
            raise ConfigError(f"Profile '{name}' does not exist.")
        del profiles[name]

        # If we deleted the active profile, switch to another or clear.
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
    with _config_lock():
        raw = _read_raw_config()

        # Handle old flat format.
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


@contextmanager
def _config_lock(timeout: float = 5.0) -> Iterator[None]:
    """Serialize config mutations across CLI processes without a dependency."""
    lock_file = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_file.open("a+b")
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise ConfigError(
                        "Timed out waiting for another CLI process to finish "
                        "updating the config."
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


def _read_raw_config() -> dict:
    """Read the raw config file as a dict."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_raw_config(data: dict) -> None:
    """Atomically write the raw config dict using a same-directory temp file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{CONFIG_FILE.name}.",
            suffix=".tmp",
            dir=CONFIG_DIR,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        os.replace(temp_name, CONFIG_FILE)
        temp_name = None
        try:
            directory_fd = os.open(CONFIG_DIR, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


class ConfigError(Exception):
    pass
