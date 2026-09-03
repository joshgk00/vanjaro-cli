"""Supported-version policy contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.reliability.artifacts import ArtifactContractError
from vanjaro_cli.reliability.compatibility import (
    load_compatibility_policy,
    validate_compatibility_policy,
)
from vanjaro_cli.reliability.contracts import PERSISTED_RUNTIME_CONTRACTS


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "release" / "compatibility-policy.json"


def test_tracked_compatibility_policy_matches_runtime_and_package_contracts() -> None:
    report = validate_compatibility_policy(POLICY, repository_root=ROOT)

    assert report.status == "passed"
    assert report.failures == ()
    assert set(report.checks.values()) == {"passed"}

    policy = load_compatibility_policy(POLICY)
    for name, schema_version in PERSISTED_RUNTIME_CONTRACTS.items():
        assert policy.contracts[name].current == schema_version
        assert schema_version in policy.contracts[name].accepted


def test_policy_rejects_missing_contract_and_unknown_fields(tmp_path: Path) -> None:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    payload["contracts"].pop("project")
    payload["unexpected"] = True
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ArtifactContractError, match="invalid compatibility policy"):
        load_compatibility_policy(path)


def test_policy_requires_named_project_migration(tmp_path: Path) -> None:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    payload["migrations"] = []
    path = ROOT / "release" / "compatibility-policy-without-migration.tmp.json"
    try:
        path.write_text(json.dumps(payload), encoding="utf-8")
        report = validate_compatibility_policy(path, repository_root=ROOT)
    finally:
        path.unlink(missing_ok=True)

    assert report.status == "failed"
    assert "project-migration:required-migration-missing" in report.failures
