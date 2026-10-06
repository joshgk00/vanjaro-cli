"""The fetched HTML of a live page is kept in the workspace (RT-19)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.orchestration.project_analysis import run_project_analysis
from vanjaro_cli.project import ProjectStage, StageContext, load_manifest
from vanjaro_cli.project.workspace import fingerprint_files

PAGE = (
    "<!doctype html><html><head><title>Live</title></head><body><main>"
    "<section><h1>Fetched headline</h1><p>Fetched copy for the page.</p></section>"
    "</main></body></html>\r\n"
)


def _context(root: Path) -> StageContext:
    return StageContext(
        root=root,
        stage=ProjectStage.ANALYZE,
        manifest=load_manifest(root),
        input_fingerprint="a" * 64,
        attempt=1,
    )


def _init(runner, root: Path, source: str) -> None:
    result = runner.invoke(
        cli,
        [
            "project", "init", str(root), "--name", "Snapshot",
            "--target-profile", "snapshot", "--source", source, "--json",
        ],
    )
    assert result.exit_code == 0, result.output


def test_fetched_page_is_saved_in_the_workspace_and_listed_as_an_artifact(
    runner, tmp_path: Path
) -> None:
    root = tmp_path / "live"
    _init(runner, root, "html=https://live.example/")

    result = run_project_analysis(_context(root), html_fetcher=lambda url: PAGE)

    saved = root / "sources" / "live-html-1" / "page.html"
    assert saved.read_bytes() == PAGE.encode("utf-8")
    assert "sources/live-html-1/page.html" in result.artifacts


def test_stage_fingerprint_changes_when_the_saved_page_changes(runner, tmp_path: Path) -> None:
    root = tmp_path / "hashed"
    _init(runner, root, "html=https://live.example/")
    run_project_analysis(_context(root), html_fetcher=lambda url: PAGE)
    page = (Path("sources/live-html-1/page.html"),)
    before = fingerprint_files(root, page)

    run_project_analysis(_context(root), html_fetcher=lambda url: PAGE.replace("Fetched", "Edited"))

    assert fingerprint_files(root, page) != before


def test_local_source_is_not_copied_again(runner, tmp_path: Path) -> None:
    saved = tmp_path / "inbox" / "home.html"
    saved.parent.mkdir()
    saved.write_text(PAGE, encoding="utf-8")
    root = tmp_path / "local"
    _init(runner, root, f"html={saved}")

    result = run_project_analysis(_context(root))

    assert not (root / "sources" / "live-html-1" / "page.html").exists()
    assert not any(path.endswith("page.html") for path in result.artifacts)
    assert json.loads((root / "analysis" / "analysis-report.json").read_text())["pages"] == 1


def test_a_failed_fetch_leaves_no_snapshot(runner, tmp_path: Path) -> None:
    root = tmp_path / "failed"
    _init(runner, root, "html=https://live.example/")

    def broken(url: str) -> str:
        raise OSError("offline")

    with pytest.raises(ValueError):
        run_project_analysis(_context(root), html_fetcher=broken)

    assert not (root / "sources" / "live-html-1" / "page.html").exists()
