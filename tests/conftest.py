"""Shared pytest fixtures."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest
import responses as resp_lib
from click.testing import CliRunner

from vanjaro_cli.config import Config

BASE_URL = "https://example.vanjaro.com"
FAKE_TOKEN = (
    # Header: {"alg":"HS256","typ":"JWT"}
    # Payload: {"sub":"admin","exp":9999999999}
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJhZG1pbiIsImV4cCI6OTk5OTk5OTk5OX0"
    ".placeholder_sig"
)
FAKE_REFRESH_TOKEN = "fake-refresh-token-abc"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_config(tmp_path: Path) -> Generator[Path, None, None]:
    """Patch the config dir to a temp directory so tests don't touch ~/.vanjaro-cli."""
    config_dir = tmp_path / ".vanjaro-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config = Config(base_url=BASE_URL, token=FAKE_TOKEN, refresh_token=FAKE_REFRESH_TOKEN)
    config_file.write_text(config.model_dump_json())

    with (
        patch("vanjaro_cli.config.CONFIG_DIR", config_dir),
        patch("vanjaro_cli.config.CONFIG_FILE", config_file),
        patch("vanjaro_cli.commands.auth_cmd.CONFIG_FILE", config_file),
    ):
        yield config_file


@pytest.fixture
def authed_config() -> Config:
    return Config(base_url=BASE_URL, token=FAKE_TOKEN, refresh_token=FAKE_REFRESH_TOKEN)


@pytest.fixture
def mocked_responses():
    """Activate the responses mock library for a test."""
    with resp_lib.RequestsMock() as rsps:
        yield rsps


# Convenience page payload matching PersonaBar API shape
def make_page(
    tab_id: int = 1,
    name: str = "Home",
    url: str = "/home",
    status: str = "published",
    level: int = 0,
) -> dict:
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
