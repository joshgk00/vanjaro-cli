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
    # Config is now stored under profiles (auto-derived from hostname)
    assert "profiles" in saved
    profile_data = next(iter(saved["profiles"].values()))
    assert profile_data["base_url"] == BASE_URL
    assert profile_data["cookies"] is not None


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
def test_login_preserves_existing_api_key_and_portal(runner, tmp_path):
    """Re-login must refresh cookies without wiping the profile's API key."""
    _mock_login_success()

    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    profile_name = "example-vanjaro-com"
    config_file.write_text(json.dumps({
        "active_profile": profile_name,
        "profiles": {
            profile_name: {
                "base_url": BASE_URL,
                "cookies": {".DOTNETNUKE": "stale-expired-cookie"},
                "api_key": "existing-api-key",
                "portal_id": 2,
            }
        },
    }))

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(
            cli,
            ["auth", "login", "--url", BASE_URL, "-u", "admin", "-p", "secret"],
        )

    assert result.exit_code == 0
    saved = json.loads(config_file.read_text())
    profile_data = saved["profiles"][profile_name]
    assert profile_data["api_key"] == "existing-api-key"
    assert profile_data["portal_id"] == 2
    assert profile_data["cookies"][".DOTNETNUKE"] == "authed-cookie-value"


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


HEALTH_URL = f"{BASE_URL}/API/VanjaroAI/AIHealth/Check"


@responses.activate
def test_status_authenticated_verifies_server(runner, mock_config):
    """Default `auth status` should ping the server and report verified=True."""
    responses.add(
        responses.GET,
        HEALTH_URL,
        json={"status": "ok", "dnn_version": "9.10.2"},
        status=200,
    )

    result = runner.invoke(cli, ["auth", "status"])

    assert result.exit_code == 0
    assert "authenticated" in result.output
    # The status check must have actually hit the server — not just the config file.
    assert any(HEALTH_URL in call.request.url for call in responses.calls)


@responses.activate
def test_status_json_includes_verified_flag(runner, mock_config):
    responses.add(responses.GET, HEALTH_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "authenticated"
    assert data["base_url"] == BASE_URL
    assert data["has_cookies"] is True
    assert data["verified"] is True


@responses.activate
def test_status_detects_expired_session(runner, mock_config):
    """Cookies present but server rejects them → session_expired, not authenticated."""
    responses.add(responses.GET, HEALTH_URL, status=401)

    result = runner.invoke(cli, ["auth", "status", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "session_expired"
    assert data["has_cookies"] is True
    assert data["verified"] is False
    assert "error" in data


@responses.activate
def test_status_human_output_for_expired_session(runner, mock_config):
    responses.add(responses.GET, HEALTH_URL, status=401)

    result = runner.invoke(cli, ["auth", "status"])

    assert result.exit_code == 0
    assert "session_expired" in result.output
    assert "vanjaro auth login" in result.output


def test_status_offline_skips_server_check(runner, mock_config):
    """`--offline` reports authenticated from local cookies without hitting the server."""
    # No HTTP mocks registered — if the command tries to call the server, the
    # `responses` library will raise, which would fail this test.
    with responses.RequestsMock() as rsps:
        result = runner.invoke(cli, ["auth", "status", "--offline", "--json"])

        assert len(rsps.calls) == 0

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "authenticated"
    assert data["has_cookies"] is True
    assert data["verified"] is False


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


def _login_with_global_profile(runner, tmp_path, monkeypatch, initial_config, *args, url=BASE_URL):
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    if initial_config is not None:
        config_file.write_text(json.dumps(initial_config))
    monkeypatch.setattr("vanjaro_cli.config._profile_override", None)

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
    ):
        result = runner.invoke(
            cli,
            [*args, "auth", "login", "--url", url, "-u", "admin", "-p", "secret"],
        )
    saved = json.loads(config_file.read_text()) if config_file.exists() else None
    return result, saved


@responses.activate
def test_login_with_global_profile_saves_into_that_profile(runner, tmp_path, monkeypatch):
    _mock_login_success()

    result, saved = _login_with_global_profile(
        runner, tmp_path, monkeypatch, None, "--profile", "my-site"
    )

    assert result.exit_code == 0, result.output
    assert list(saved["profiles"]) == ["my-site"]
    assert saved["profiles"]["my-site"]["base_url"] == BASE_URL
    assert saved["profiles"]["my-site"]["cookies"][".DOTNETNUKE"] == "authed-cookie-value"
    assert saved["active_profile"] == "my-site"


@responses.activate
def test_login_with_global_profile_leaves_hostname_profile_untouched(
    runner, tmp_path, monkeypatch
):
    _mock_login_success()
    hostname_profile = {"base_url": BASE_URL, "cookies": {".DOTNETNUKE": "old"}, "portal_id": 0}
    initial = {
        "active_profile": "example-vanjaro-com",
        "profiles": {
            "example-vanjaro-com": hostname_profile,
            "child": {"base_url": BASE_URL, "api_key": "child-key", "portal_id": 3},
        },
    }

    result, saved = _login_with_global_profile(
        runner, tmp_path, monkeypatch, initial, "--profile", "child"
    )

    assert result.exit_code == 0, result.output
    assert saved["profiles"]["example-vanjaro-com"] == hostname_profile
    assert saved["profiles"]["child"]["api_key"] == "child-key"
    assert saved["profiles"]["child"]["portal_id"] == 3
    assert saved["profiles"]["child"]["cookies"][".DOTNETNUKE"] == "authed-cookie-value"


@responses.activate
def test_login_with_global_profile_refuses_different_base_url(runner, tmp_path, monkeypatch):
    _mock_login_success()
    initial = {
        "active_profile": "vanjarocli-local",
        "profiles": {"vanjarocli-local": {"base_url": "http://vanjarocli.local", "portal_id": 0}},
    }

    result, saved = _login_with_global_profile(
        runner,
        tmp_path,
        monkeypatch,
        initial,
        "--profile",
        "vanjarocli-local",
        url="http://vanjarocli.local/keys-to-success",
    )

    assert result.exit_code != 0
    assert "vanjarocli-local" in result.output
    assert "http://vanjarocli.local" in result.output
    assert "Drop --profile" in result.output
    assert saved == initial
    assert len(responses.calls) == 0


@responses.activate
def test_login_with_global_profile_accepts_same_base_url_with_trailing_slash(
    runner, tmp_path, monkeypatch
):
    _mock_login_success()
    initial = {
        "active_profile": "p",
        "profiles": {"p": {"base_url": BASE_URL, "portal_id": 1}},
    }

    result, saved = _login_with_global_profile(
        runner, tmp_path, monkeypatch, initial, "--profile", "p", url=BASE_URL + "/"
    )

    assert result.exit_code == 0, result.output
    assert saved["profiles"]["p"]["portal_id"] == 1
    assert saved["profiles"]["p"]["cookies"]


@responses.activate
def test_login_without_global_profile_still_uses_hostname_profile(runner, tmp_path, monkeypatch):
    _mock_login_success()

    result, saved = _login_with_global_profile(runner, tmp_path, monkeypatch, None)

    assert result.exit_code == 0, result.output
    assert list(saved["profiles"]) == ["example-vanjaro-com"]
