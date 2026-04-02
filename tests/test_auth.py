"""Tests for vanjaro auth commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, FAKE_TOKEN, FAKE_REFRESH_TOKEN


LOGIN_URL = f"{BASE_URL}/API/JwtAuth/Login"
LOGOUT_URL = f"{BASE_URL}/API/JwtAuth/LogOut"


@responses.activate
def test_login_success(runner, tmp_path):
    responses.add(
        responses.POST,
        LOGIN_URL,
        json={"Token": FAKE_TOKEN, "RenewToken": FAKE_REFRESH_TOKEN, "DisplayName": "Admin"},
        status=200,
    )
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.auth.save_config"),
    ):
        result = runner.invoke(
            cli,
            ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "secret"],
        )

    assert result.exit_code == 0
    assert "Logged in" in result.output


@responses.activate
def test_login_json_output(runner, tmp_path):
    responses.add(
        responses.POST,
        LOGIN_URL,
        json={"Token": FAKE_TOKEN, "RenewToken": FAKE_REFRESH_TOKEN},
        status=200,
    )
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.auth.save_config"),
    ):
        result = runner.invoke(
            cli,
            ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "secret", "--json"],
        )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["base_url"] == BASE_URL


@responses.activate
def test_login_bad_credentials(runner, tmp_path):
    responses.add(responses.POST, LOGIN_URL, status=401)

    result = runner.invoke(
        cli,
        ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "wrong"],
    )

    assert result.exit_code == 1


def test_logout_clears_token(runner, mock_config):
    with patch("vanjaro_cli.commands.auth_cmd.logout"):
        result = runner.invoke(cli, ["auth", "logout"])

    assert result.exit_code == 0
    assert "Logged out" in result.output


def test_logout_json(runner, mock_config):
    with patch("vanjaro_cli.commands.auth_cmd.logout"):
        result = runner.invoke(cli, ["auth", "logout", "--json"])

    data = json.loads(result.output)
    assert data["status"] == "ok"


def test_status_authenticated(runner, mock_config):
    result = runner.invoke(cli, ["auth", "status"])
    assert result.exit_code == 0
    assert "authenticated" in result.output


def test_status_json(runner, mock_config):
    result = runner.invoke(cli, ["auth", "status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "authenticated"
    assert data["base_url"] == BASE_URL
    assert data["has_token"] is True


def test_status_not_logged_in(runner, tmp_path):
    config_file = tmp_path / "config.json"  # does not exist
    with (
        patch("vanjaro_cli.config.CONFIG_DIR", tmp_path),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["auth", "status"])

    assert "Not logged in" in result.output or "unauthenticated" in result.output


@responses.activate
def test_login_missing_url(runner):
    result = runner.invoke(cli, ["auth", "login", "-u", "admin", "-p", "secret"])
    assert result.exit_code != 0
