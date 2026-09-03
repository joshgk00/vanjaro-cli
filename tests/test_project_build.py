"""Regression tests for project build-stage orchestration glue."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from vanjaro_cli.orchestration import project_build
from vanjaro_cli.project.stage_engine import StageResult


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_register_library_stage_returns_artifacts_after_portal_reconcile(
    tmp_path: Path, monkeypatch
) -> None:
    _write_json(tmp_path / "build/library-plan.json", [])
    verified = SimpleNamespace(
        portal_id=2,
        as_dict=lambda: {"portal_id": 2, "base_url": "http://portal.test"},
    )
    monkeypatch.setattr(
        project_build,
        "verify_project_portal",
        lambda manifest: (object(), verified),
    )
    monkeypatch.setattr(
        project_build,
        "register_project_library",
        lambda client, **kwargs: (
            [{"key": "home.hero", "name": "Project / Hero"}],
            [{"key": "home.hero", "name": "Project / Hero", "status": "reused"}],
        ),
    )
    context = SimpleNamespace(root=tmp_path, manifest=object())

    result = project_build.register_project_library_stage(context)

    assert isinstance(result, StageResult)
    assert result.artifacts == (
        "build/block-manifest.json",
        "build/composed-blocks.json",
        "build/library-result.json",
    )
    assert json.loads((tmp_path / "build/library-result.json").read_text())[
        "published"
    ] is False


def test_latest_page_manifest_path_uses_downstream_global_version(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "build/page-manifest.json"
    downstream = tmp_path / "build/global-page-manifest.json"
    _write_json(primary, {"pages": [{"observed_version": 3}]})
    _write_json(downstream, {"pages": [{"observed_version": 5}]})

    assert project_build._latest_page_manifest_path(tmp_path) == downstream

    _write_json(primary, {"pages": [{"observed_version": 6}]})
    assert project_build._latest_page_manifest_path(tmp_path) == primary


def test_unresolved_global_guids_are_receipted_as_parameterized_page_work() -> None:
    action = {
        "key": "home",
        "action": "update",
        "desired_hash": "a" * 64,
        "desired_state_fingerprint": "b" * 64,
        "payload_fingerprint": "c" * 64,
        "operations": [
            {
                "sequence": 1,
                "kind": "portal_request",
                "payload_fingerprint": "c" * 64,
            }
        ],
    }

    planned = project_build._parameterize_page_action(
        action, ["agency-binding://global/header"]
    )

    assert planned["action"] == "resolve_bindings_then_reconcile"
    assert planned["provisional_action"] == "update"
    assert planned["resolved_payload_fingerprint"] is None
    assert "desired_hash" not in planned
    assert planned["template_preview_hash"] == "a" * 64
    assert "payload_fingerprint" not in planned
    assert planned["payload_template_fingerprint"] == "c" * 64
    assert (
        planned["operations"][0]["global_guid_bindings"]
        == ["agency-binding://global/header"]
    )
