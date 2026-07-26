"""Filesystem and fingerprint tests for agency project workspaces."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.project import (
    MANIFEST_FILENAME,
    ProjectSource,
    ProjectWorkspaceError,
    WORKSPACE_DIRECTORIES,
    artifact_path,
    create_manifest,
    fingerprint_data,
    fingerprint_files,
    initialize_workspace,
    load_manifest,
    workspace_status,
    write_manifest,
)


NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _manifest():
    return create_manifest(
        name="Workspace Test",
        target_profile="workspace-test",
        sources=[
            ProjectSource(
                id="live-html-1",
                kind=SourceKind.LIVE_HTML,
                reference="https://agency.example/",
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
        clock=lambda: NOW,
    )


def test_workspace_initialization_is_complete_loadable_and_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "project"
    manifest = _manifest()
    path = initialize_workspace(root, manifest)

    assert path == root / MANIFEST_FILENAME
    assert all((root / directory).is_dir() for directory in WORKSPACE_DIRECTORIES)
    assert load_manifest(root) == manifest
    first_bytes = path.read_bytes()
    write_manifest(root, manifest)
    assert path.read_bytes() == first_bytes

    status = workspace_status(root)
    assert status.completed_stages == ("intake",)
    assert status.next_stage == "analyze"
    assert status.target_profile == "workspace-test"
    assert status.missing_directories == ()


def test_workspace_initialization_never_overwrites_nonempty_directory(tmp_path: Path) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    existing = root / "keep.txt"
    existing.write_text("owned by user", encoding="utf-8")

    with pytest.raises(ProjectWorkspaceError, match="not empty"):
        initialize_workspace(root, _manifest())

    assert existing.read_text(encoding="utf-8") == "owned by user"
    assert not (root / MANIFEST_FILENAME).exists()


def test_fingerprints_are_order_independent_and_paths_cannot_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")

    assert fingerprint_data({"b": 2, "a": 1}) == fingerprint_data({"a": 1, "b": 2})
    assert fingerprint_files(root, [Path("a.txt"), Path("b.txt")]) == fingerprint_files(
        root, [Path("b.txt"), Path("a.txt")]
    )
    with pytest.raises(ProjectWorkspaceError, match="escapes"):
        fingerprint_files(root, [tmp_path / "outside.txt"])
    with pytest.raises(ProjectWorkspaceError, match="escapes"):
        artifact_path(root, "../outside.json")
