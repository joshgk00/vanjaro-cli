"""Tests for config module — profile management, migration, API key storage."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

# Env vars that load_config() checks — must be cleared during tests
_VANJARO_ENV_VARS = ("VANJARO_BASE_URL", "VANJARO_TOKEN", "VANJARO_PORTAL_ID")

from vanjaro_cli.config import (
    Config,
    ConfigError,
    clear_session,
    delete_profile,
    derive_profile_name,
    list_profiles,
    load_config,
    save_config,
    set_active_profile,
    save_api_key,
    remove_api_key,
)


@pytest.fixture
def config_dir(tmp_path: Path):
    """Set up a temporary config directory with env var isolation."""
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    saved_env = {k: os.environ.pop(k) for k in _VANJARO_ENV_VARS if k in os.environ}

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.config._profile_override", None),
    ):
        yield config_file

    os.environ.update(saved_env)


def test_derive_profile_name_from_hostname():
    assert derive_profile_name("http://vanjarocli.local") == "vanjarocli-local"
    assert derive_profile_name("https://staging.example.com") == "staging-example-com"
    assert derive_profile_name("http://localhost:8085") == "localhost"


def test_save_and_load_config(config_dir):
    config = Config(base_url="http://test.local", cookies={"auth": "cookie"})
    save_config(config, "test-site")

    loaded = load_config("test-site")
    assert loaded.base_url == "http://test.local"
    assert loaded.cookies == {"auth": "cookie"}


def test_save_creates_profile_format(config_dir):
    config = Config(base_url="http://test.local")
    save_config(config, "mysite")

    raw = json.loads(config_dir.read_text())
    assert "profiles" in raw
    assert "mysite" in raw["profiles"]
    assert raw["active_profile"] == "mysite"


def test_save_config_sets_active_on_login(config_dir):
    """When saving with cookies (login), the profile becomes active."""
    config1 = Config(base_url="http://site1.local")
    save_config(config1, "site1")

    config2 = Config(base_url="http://site2.local", cookies={"auth": "token"})
    save_config(config2, "site2")

    raw = json.loads(config_dir.read_text())
    assert raw["active_profile"] == "site2"


def test_save_config_can_preserve_active_profile_in_one_write(config_dir):
    save_config(Config(base_url="https://host", cookies={"auth": "one"}), "host")
    from vanjaro_cli import config as config_module

    with patch(
        "vanjaro_cli.config._write_raw_config",
        wraps=config_module._write_raw_config,
    ) as write:
        save_config(
            Config(base_url="https://host/child", cookies={"auth": "one"}, portal_id=4),
            "child",
            preserve_active_profile=True,
        )
    assert write.call_count == 1
    raw = json.loads(config_dir.read_text())
    assert raw["active_profile"] == "host"
    assert raw["profiles"]["child"]["portal_id"] == 4


def test_save_config_conditionally_refuses_a_new_collision(config_dir):
    save_config(Config(base_url="https://host/child"), "child")

    with pytest.raises(ConfigError, match="created after preview"):
        save_config(
            Config(base_url="https://other/child"),
            "child",
            replace_existing=False,
        )

    assert load_config("child").base_url == "https://host/child"


def test_concurrent_profile_saves_merge_under_lock(config_dir):
    def save(index: int) -> None:
        save_config(Config(base_url=f"https://site-{index}.example"), f"site-{index}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, range(20)))

    raw = json.loads(config_dir.read_text())
    assert set(raw["profiles"]) == {f"site-{index}" for index in range(20)}


def test_independent_process_profile_saves_merge_under_lock(config_dir):
    script = """
import sys
from pathlib import Path
import vanjaro_cli.config as module

module.CONFIG_FILE = Path(sys.argv[1])
module.CONFIG_DIR = module.CONFIG_FILE.parent
module.save_config(
    module.Config(base_url=f\"https://process-{sys.argv[2]}.example\"),
    f\"process-{sys.argv[2]}\",
)
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(config_dir), str(index)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(8)
    ]
    failures = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        if process.returncode:
            failures.append((process.returncode, stdout, stderr))

    assert failures == []
    raw = json.loads(config_dir.read_text())
    assert set(raw["profiles"]) == {f"process-{index}" for index in range(8)}


def test_atomic_write_cleans_temporary_file_on_replace_failure(config_dir):
    from vanjaro_cli.config import _write_raw_config

    with patch("vanjaro_cli.config.os.replace", side_effect=OSError("replace failed")):
        with pytest.raises(OSError, match="replace failed"):
            _write_raw_config({"profiles": {}})
    assert list(config_dir.parent.glob(f".{config_dir.name}.*.tmp")) == []


def test_load_config_nonexistent_profile(config_dir):
    config = Config(base_url="http://test.local")
    save_config(config, "exists")

    with pytest.raises(ConfigError, match="not found"):
        load_config("nonexistent")


def test_load_config_no_config_file(config_dir):
    with pytest.raises(ConfigError, match="No base URL configured"):
        load_config()


def test_backward_compatible_flat_format(config_dir):
    """Old flat config format should load as 'default' profile."""
    config_dir.write_text(json.dumps({
        "base_url": "http://old.site",
        "cookies": {"auth": "old-cookie"},
        "portal_id": 0,
    }))

    config = load_config()
    assert config.base_url == "http://old.site"
    assert config.cookies == {"auth": "old-cookie"}


def test_flat_format_migration_on_save(config_dir):
    """Saving to a flat-format config should migrate it to profiles format."""
    config_dir.write_text(json.dumps({
        "base_url": "http://old.site",
        "cookies": {"auth": "old"},
        "portal_id": 0,
    }))

    new_config = Config(base_url="http://new.site", cookies={"auth": "new"})
    save_config(new_config, "new-site")

    raw = json.loads(config_dir.read_text())
    assert "profiles" in raw
    assert "default" in raw["profiles"]
    assert "new-site" in raw["profiles"]


def test_set_active_profile(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")
    save_config(Config(base_url="http://b.local"), "site-b")

    set_active_profile("site-a")

    raw = json.loads(config_dir.read_text())
    assert raw["active_profile"] == "site-a"


def test_set_active_profile_nonexistent(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")

    with pytest.raises(ConfigError, match="does not exist"):
        set_active_profile("nonexistent")


def test_delete_profile(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")
    save_config(Config(base_url="http://b.local"), "site-b")

    delete_profile("site-b")

    raw = json.loads(config_dir.read_text())
    assert "site-b" not in raw["profiles"]
    assert "site-a" in raw["profiles"]


def test_delete_active_profile_switches(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")
    save_config(Config(base_url="http://b.local"), "site-b")
    set_active_profile("site-a")

    delete_profile("site-a")

    raw = json.loads(config_dir.read_text())
    assert raw["active_profile"] == "site-b"


def test_delete_nonexistent_profile(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")

    with pytest.raises(ConfigError, match="does not exist"):
        delete_profile("nonexistent")


def test_list_profiles_multiple(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")
    save_config(Config(base_url="http://b.local"), "site-b")
    set_active_profile("site-a")

    profiles = list_profiles()

    assert len(profiles) == 2
    active = [p for p in profiles if p["active"]]
    assert len(active) == 1
    assert active[0]["name"] == "site-a"


def test_list_profiles_empty(config_dir):
    profiles = list_profiles()
    assert profiles == []


def test_list_profiles_flat_format(config_dir):
    config_dir.write_text(json.dumps({"base_url": "http://old.site"}))

    profiles = list_profiles()

    assert len(profiles) == 1
    assert profiles[0]["name"] == "default"
    assert profiles[0]["active"] is True


def test_clear_session_profiles_format(config_dir):
    save_config(Config(base_url="http://a.local", cookies={"auth": "cookie"}), "site-a")

    clear_session("site-a")

    loaded = load_config("site-a")
    assert loaded.cookies is None
    assert loaded.base_url == "http://a.local"


def test_clear_session_flat_format(config_dir):
    config_dir.write_text(json.dumps({
        "base_url": "http://old.site",
        "cookies": {"auth": "old"},
    }))

    clear_session()

    raw = json.loads(config_dir.read_text())
    assert "cookies" not in raw
    assert raw["base_url"] == "http://old.site"


def test_save_api_key(config_dir):
    save_config(Config(base_url="http://a.local"), "site-a")

    save_api_key("my-api-key", "site-a")

    loaded = load_config("site-a")
    assert loaded.api_key == "my-api-key"


def test_remove_api_key(config_dir):
    save_config(Config(base_url="http://a.local", api_key="old-key"), "site-a")

    remove_api_key("site-a")

    loaded = load_config("site-a")
    assert loaded.api_key is None


def test_config_has_api_key_property():
    config_with = Config(base_url="http://test.local", api_key="key")
    config_without = Config(base_url="http://test.local")

    assert config_with.has_api_key is True
    assert config_without.has_api_key is False


def test_config_strips_trailing_slash():
    config = Config(base_url="http://test.local/")
    assert config.base_url == "http://test.local"


def test_load_config_prefers_profile_values_over_env(config_dir):
    save_config(
        Config(
            base_url="http://baseline.local",
            cookies={"auth": "cookie"},
            portal_id=7,
        ),
        "baseline",
    )

    os.environ["VANJARO_BASE_URL"] = "http://wrong.local"
    os.environ["VANJARO_PORTAL_ID"] = "99"

    loaded = load_config("baseline")

    assert loaded.base_url == "http://baseline.local"
    assert loaded.portal_id == 7
    assert loaded.cookies == {"auth": "cookie"}

    os.environ.pop("VANJARO_BASE_URL", None)
    os.environ.pop("VANJARO_PORTAL_ID", None)
