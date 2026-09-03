"""Deterministic, explicit launch-intent planning contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_project_handoff import _refresh_stage_fingerprint, _workspace, _write
from tests.test_portal_pages import _document
from vanjaro_cli.design.models import NavigationVisibility
from vanjaro_cli.design.serialization import write_design_document
from vanjaro_cli.orchestration.project_launch_plan import (
    ProjectLaunchPlanError,
    create_project_launch_plan,
)
from vanjaro_cli.project import ProjectStage, load_manifest, write_manifest
from vanjaro_cli.project.launch_plan import LaunchPlanError, build_launch_plan


def _launch_workspace(tmp_path: Path, *, visibility=NavigationVisibility.VISIBLE) -> Path:
    root = _workspace(tmp_path)
    document = _document()
    page = document.pages[0].model_copy(
        update={"navigation_visibility": visibility}
    )
    document = document.model_copy(update={"pages": [page]})
    design_path = root / "plans/resolved-design-document.json"
    write_design_document(design_path, document)
    manifest = load_manifest(root)
    manifest.stages[ProjectStage.PLAN].artifacts.append(
        "plans/resolved-design-document.json"
    )
    write_manifest(root, manifest)
    _refresh_stage_fingerprint(root, ProjectStage.PLAN)
    page_path = root / "build/global-page-manifest.json"
    page_manifest = json.loads(page_path.read_text(encoding="utf-8"))
    page_manifest["pages"][0]["key"] = document.pages[0].id
    _write(page_path, page_manifest)
    _refresh_stage_fingerprint(root, ProjectStage.GLOBAL_BLOCKS)
    return root


def test_launch_plan_dry_run_is_deterministic_and_zero_write(tmp_path: Path) -> None:
    root = _launch_workspace(tmp_path)
    before = (root / "project.json").read_bytes()

    first = create_project_launch_plan(
        root,
        home_page_key="home",
        preserve_current_home=False,
        dry_run=True,
    )
    second = create_project_launch_plan(
        root,
        home_page_key="home",
        preserve_current_home=False,
        dry_run=True,
    )

    assert first == second
    assert first["plan"]["pages"][0] == {
        "page_key": "home",
        "page_id": 101,
        "source_slug": "home",
        "desired_name": "Home",
        "desired_title": "Home",
        "parent_key": None,
        "parent_id": None,
        "navigation_visible": True,
        "navigation_order": 0,
    }
    assert not (root / "plans/launch-plan.json").exists()
    assert (root / "project.json").read_bytes() == before


def test_launch_plan_requires_explicit_unknown_visibility_override(
    tmp_path: Path,
) -> None:
    root = _launch_workspace(tmp_path, visibility=NavigationVisibility.UNKNOWN)

    with pytest.raises(ProjectLaunchPlanError, match="unknown navigation visibility"):
        create_project_launch_plan(
            root,
            home_page_key="home",
            preserve_current_home=False,
            dry_run=True,
        )

    result = create_project_launch_plan(
        root,
        home_page_key="home",
        preserve_current_home=False,
        visibility_overrides={"home": True},
        dry_run=True,
    )
    assert result["plan"]["pages"][0]["navigation_visible"] is True


def test_launch_plan_adoption_is_idempotent_and_invalidates_only_launch(
    tmp_path: Path,
) -> None:
    root = _launch_workspace(tmp_path)

    first = create_project_launch_plan(
        root,
        home_page_key="home",
        preserve_current_home=False,
    )
    after_first = (root / "project.json").read_bytes()
    second = create_project_launch_plan(
        root,
        home_page_key="home",
        preserve_current_home=False,
    )

    assert first["workspace_mutated"] is True
    assert second["workspace_mutated"] is False
    assert (root / "project.json").read_bytes() == after_first
    manifest = load_manifest(root)
    assert manifest.metadata["launch_plan"]["fingerprint"] == first["plan"]["fingerprint"]
    assert manifest.stages[ProjectStage.PUBLISH].status.value == "pending"
    assert manifest.stages[ProjectStage.LAUNCH].status.value == "pending"


def test_pure_plan_rejects_hidden_home_page() -> None:
    document = _document()
    with pytest.raises(ValueError, match="home page must be visible"):
        build_launch_plan(
            document,
            [{"key": "home", "page_id": 101}],
            project_id="agency",
            design_document_sha256="a" * 64,
            page_manifest_sha256="b" * 64,
            home_page_key="home",
            preserve_current_home=False,
            visibility_overrides={"home": False},
        )


def test_pure_plan_rejects_unknown_override_key() -> None:
    with pytest.raises(LaunchPlanError, match="unknown page key"):
        build_launch_plan(
            _document(),
            [{"key": "home", "page_id": 101}],
            project_id="agency",
            design_document_sha256="a" * 64,
            page_manifest_sha256="b" * 64,
            home_page_key="home",
            preserve_current_home=False,
            name_overrides={"missing": "Missing"},
        )
