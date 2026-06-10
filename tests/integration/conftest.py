"""Fixtures for live integration tests against a real Vanjaro instance.

These tests exist to catch URL, endpoint, and field-name drift that mocked
unit tests cannot — the `responses` mocks are built from the same assumptions
the code makes, so both drift together.

The whole suite self-skips when the target site is unreachable or the stored
session has expired. Select the profile with the ``VANJARO_TEST_PROFILE``
environment variable (default: ``vanjarocli-local``).
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from click.testing import CliRunner, Result

from vanjaro_cli.cli import cli
from vanjaro_cli.config import set_profile_override

PROFILE = os.environ.get("VANJARO_TEST_PROFILE", "vanjarocli-local")


def _invoke(runner: CliRunner, args: tuple[str, ...]) -> Result:
    """Invoke the CLI, then clear the module-global profile override.

    The --profile flag sets vanjaro_cli.config._profile_override and never
    resets it — harmless in a one-shot CLI process, but it leaks into every
    later in-process CliRunner invocation and breaks the unit tests' mocked
    "default" profile when both suites run together.
    """
    try:
        return runner.invoke(cli, ["--profile", PROFILE, *args])
    finally:
        set_profile_override(None)


class LiveCli:
    """Invoke the CLI against the live test profile with assertion helpers."""

    def __init__(self, runner: CliRunner) -> None:
        self.runner = runner

    def run(self, *args: str) -> Result:
        return _invoke(self.runner, args)

    def run_ok(self, *args: str) -> Result:
        result = self.run(*args)
        assert result.exit_code == 0, (
            f"`vanjaro {' '.join(args)}` failed (exit {result.exit_code}):\n{result.output}"
        )
        return result

    def run_json(self, *args: str) -> dict | list:
        result = self.run_ok(*args, "--json")
        return json.loads(result.output)


def unique_name(prefix: str) -> str:
    """Collision-proof resource name so parallel/aborted runs never clash."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def live_site_available() -> None:
    """Gate the suite on a successful health check against the live site."""
    result = _invoke(CliRunner(), ("site", "health", "--json"))
    if result.exit_code != 0:
        pytest.skip(
            f"Live site unavailable for profile '{PROFILE}': {result.output.strip()} "
            f"— run `vanjaro auth login` (and `vanjaro api-key set` if needed), "
            f"or set VANJARO_TEST_PROFILE to a working profile."
        )


@pytest.fixture
def live_cli(live_site_available: None) -> LiveCli:
    return LiveCli(CliRunner())
