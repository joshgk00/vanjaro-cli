"""Tests for vanjaro auth commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, FAKE_COOKIES

LOGIN_PAGE_URL = f"{BASE_URL}/Login"
LOGIN_API_URL = f"{BASE_URL}/API/Login/Login/UserLogin"

# Minimal DNN login page HTML with anti-forgery token and tabId
FAKE_LOGIN_PAGE = (
    '<html><body><form>'
    '<input name="__RequestVerificationToken" type="hidden" value="fake-rv-token" />'
    '<input name="__dnnVariable" type="hidden" value="`{`sf_tabId`:`33`}" />'
    '</form></body></html>'
)


def _mock_login_success():
    """Mock a successful Vanjaro login flow."""
    responses.add(responses.GET, LOGIN_PAGE_URL, body=FAKE_LOGIN_PAGE, status=200)
    responses.add(
        responses.POST,
        LOGIN_API_URL,
        json={"IsSuccess": True, "IsRedirect": True, "RedirectURL": f"{BASE_URL}/"},
        status=200,
        headers={"Set-Cookie": ".DOTNETNUKE=authed-cookie-value; path=/"},
    )


@responses.activate
def test_login_success(runner, tmp_path):
    _mock_login_success()

    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(
            cli,
            ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "secret"],
        )

    assert result.exit_code == 0
    assert "Logged in" in result.output

    assert config_file.exists()
    saved = json.loads(config_file.read_text())
    assert saved["base_url"] == BASE_URL
    assert saved["cookies"] is not None


@responses.activate
def test_login_sends_correct_payload(runner, tmp_path):
    _mock_login_success()

    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
    ):
        runner.invoke(
            cli,
            ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "secret"],
        )

    api_call = [c for c in responses.calls if "UserLogin" in c.request.url][0]
    sent_body = json.loads(api_call.request.body)
    assert sent_body["Username"] == "admin"
    assert sent_body["Password"] == "secret"
    assert api_call.request.headers["RequestVerificationToken"] == "fake-rv-token"
    assert api_call.request.headers["TabId"] == "33"


@responses.activate
def test_login_json_output(runner, tmp_path):
    _mock_login_success()

    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
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
    responses.add(responses.GET, LOGIN_PAGE_URL, body=FAKE_LOGIN_PAGE, status=200)
    responses.add(
        responses.POST,
        LOGIN_API_URL,
        json={"IsSuccess": False, "HasErrors": True, "Message": "Invalid credentials"},
        status=200,
    )

    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(
            cli,
            ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "wrong"],
        )

    assert result.exit_code == 1


def test_logout_clears_session(runner, mock_config):
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
    assert data["has_cookies"] is True


def test_status_not_logged_in(runner, tmp_path):
    config_file = tmp_path / "config.json"
    with (
        patch("vanjaro_cli.config.CONFIG_DIR", tmp_path),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(cli, ["auth", "status"])

    assert "Not logged in" in result.output


@responses.activate
def test_login_missing_url(runner):
    result = runner.invoke(cli, ["auth", "login", "-u", "admin", "-p", "secret"])
    assert result.exit_code != 0
