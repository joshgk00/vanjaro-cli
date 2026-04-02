"""Tests for vanjaro profile commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, FAKE_COOKIES, _build_profile_config


def _write_multi_profile_config(config_file: Path) -> None:
    """Write a config with multiple profiles."""
    config_data = {
        "active_profile": "local",
        "profiles": {
            "local": {
                "base_url": "http://vanjarocli.local",
                "cookies": FAKE_COOKIES,
                "portal_id": 0,
            },
            "staging": {
                "base_url": "https://staging.example.com",
                "cookies": FAKE_COOKIES,
                "portal_id": 0,
            },
        },
    }
    config_file.write_text(json.dumps(config_data))


def test_profile_list(runner, mock_config):
    result = runner.invoke(cli, ["profile", "list"])

    assert result.exit_code == 0
    assert "default" in result.output
    assert BASE_URL in result.output


def test_profile_list_json(runner, mock_config):
    result = runner.invoke(cli, ["profile", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["name"] == "default"
    assert data[0]["base_url"] == BASE_URL
    assert data[0]["active"] is True


def test_profile_list_multiple(runner, tmp_path):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _write_multi_profile_config(config_file)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "list"])

    assert result.exit_code == 0
    assert "local" in result.output
    assert "staging" in result.output
    assert "*" in result.output


def test_profile_use(runner, tmp_path):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _write_multi_profile_config(config_file)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "use", "staging"])

    assert result.exit_code == 0
    assert "Switched to profile 'staging'" in result.output

    saved = json.loads(config_file.read_text())
    assert saved["active_profile"] == "staging"


def test_profile_use_nonexistent(runner, mock_config):
    result = runner.invoke(cli, ["profile", "use", "nonexistent"])
    assert result.exit_code == 1


def test_profile_delete_with_force(runner, tmp_path):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _write_multi_profile_config(config_file)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "delete", "staging", "--force"])

    assert result.exit_code == 0
    assert "Deleted profile 'staging'" in result.output

    saved = json.loads(config_file.read_text())
    assert "staging" not in saved["profiles"]
    assert "local" in saved["profiles"]


def test_profile_delete_prompts_without_force(runner, tmp_path):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _write_multi_profile_config(config_file)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "delete", "staging"], input="y\n")

    assert result.exit_code == 0


def test_profile_delete_abort(runner, tmp_path):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _write_multi_profile_config(config_file)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "delete", "staging"], input="n\n")

    assert result.exit_code != 0


def test_profile_delete_nonexistent(runner, mock_config):
    result = runner.invoke(cli, ["profile", "delete", "nonexistent", "--force"])
    assert result.exit_code == 1


def test_profile_delete_active_switches(runner, tmp_path):
    """Deleting the active profile should switch to another available profile."""
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    _write_multi_profile_config(config_file)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "delete", "local", "--force"])

    assert result.exit_code == 0
    saved = json.loads(config_file.read_text())
    assert saved["active_profile"] == "staging"


def test_profile_list_empty(runner, tmp_path):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"active_profile": "", "profiles": {}}))

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["profile", "list"])

    assert result.exit_code == 0
    assert "No profiles configured" in result.output
