"""Shared pytest fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
import responses as resp_lib
from click.testing import CliRunner

from vanjaro_cli.config import Config

BASE_URL = "https://example.vanjaro.com"
FAKE_COOKIES = {".DOTNETNUKE": "fake-auth-cookie-abc", "__RequestVerificationToken": "fake-rv-cookie"}
FAKE_ANTIFORGERY_TOKEN = "fake-antiforgery-token-xyz"

# HTML snippet that mimics a DNN page with an anti-forgery token
FAKE_HOMEPAGE_HTML = (
    '<html><body><form>'
    f'<input name="__RequestVerificationToken" type="hidden" value="{FAKE_ANTIFORGERY_TOKEN}" />'
    '</form></body></html>'
)

# Env vars that load_config() checks — must be cleared during tests
# so a local .env file doesn't override the test config
_VANJARO_ENV_VARS = ("VANJARO_BASE_URL", "VANJARO_TOKEN", "VANJARO_PORTAL_ID")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path) -> Generator[Path, None, None]:
    """Patch the config dir to a temp directory so tests don't touch ~/.vanjaro-cli."""
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config = Config(base_url=BASE_URL, cookies=FAKE_COOKIES)
    config_file.write_text(config.model_dump_json())

    # Save and clear any env vars that would override the test config
    saved_env = {k: os.environ.pop(k) for k in _VANJARO_ENV_VARS if k in os.environ}

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        yield config_file

    # Restore any env vars we cleared
    os.environ.update(saved_env)


@pytest.fixture
def authed_config() -> Config:
    return Config(base_url=BASE_URL, cookies=FAKE_COOKIES)


@pytest.fixture
def mocked_responses():
    """Activate the responses mock library for a test."""
    with resp_lib.RequestsMock() as rsps:
        yield rsps


def mock_homepage(rsps: resp_lib.RequestsMock | None = None) -> None:
    """Register a mock for the homepage that returns an anti-forgery token."""
    target = rsps if rsps is not None else resp_lib
    target.add(
        resp_lib.GET,
        f"{BASE_URL}/",
        body=FAKE_HOMEPAGE_HTML,
        status=200,
    )


def make_page_item(
    tab_id: int = 1,
    name: str = "Home",
    level: int = 0,
) -> dict:
    """Build a page item matching the Vanjaro GetPages response format."""
    prefix = "-  " * level
    return {
        "Text": f"{prefix}{name}",
        "Value": tab_id,
        "Url": None,
    }


def make_page_detail(
    tab_id: int = 1,
    name: str = "Home",
    url: str = "/home",
    status: str = "published",
    level: int = 0,
) -> dict:
    """Build a page payload matching the PersonaBar GetPageDetails format."""
    return {
        "tabId": tab_id,
        "name": name,
        "title": name,
        "url": url,
        "parentId": None,
        "isDeleted": False,
        "includeInMenu": True,
        "status": status,
        "level": level,
        "hasChildren": False,
        "portalId": 0,
        "startDate": None,
        "endDate": None,
    }
