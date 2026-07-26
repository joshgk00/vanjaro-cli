"""CliRunner coverage for Design Document crawl and offline analysis."""

from __future__ import annotations

import json
from pathlib import Path

import responses

from vanjaro_cli.cli import cli
from vanjaro_cli.design.serialization import read_design_document

from .test_migrate_crawl_cmd import SOURCE_URL, _register_site


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_legacy_directory(tmp_path: Path, *, missing_section: bool = False) -> Path:
    section_path = "pages/home/section-001-hero.json"
    _write_json(
        tmp_path / "site-inventory.json",
        {
            "source_url": "https://legacy.example/",
            "crawled_at": "2026-07-16T12:00:00+00:00",
            "pages": [
                {
                    "url": "https://legacy.example/",
                    "slug": "home",
                    "title": "Legacy Home",
                    "parent_slug": None,
                    "sections": [
                        {
                            "file": (
                                "pages/home/missing.json"
                                if missing_section
                                else section_path
                            ),
                            "type": "hero",
                            "template": "Centered Hero",
                        }
                    ],
                }
            ],
            "assets": {"manifest": "assets/manifest.json"},
            "global": {},
        },
    )
    if not missing_section:
        _write_json(
            tmp_path / section_path,
            {
                "type": "hero",
                "template": "Centered Hero",
                "content": {
                    "headings": ["Welcome"],
                    "paragraphs": ["Hello"],
                    "images": [],
                    "buttons": [],
                },
            },
        )
    _write_json(tmp_path / "assets" / "manifest.json", [])
    return tmp_path


def test_migrate_analyze_writes_default_output(runner, tmp_path: Path) -> None:
    artifact_dir = _make_legacy_directory(tmp_path)

    result = runner.invoke(cli, ["migrate", "analyze", str(artifact_dir)])

    assert result.exit_code == 0, result.output
    output = artifact_dir / "design-document.json"
    assert output.is_file()
    document = read_design_document(output)
    assert document.schema_version == "1.0"
    assert document.pages[0].sections[0].semantic_role == "hero"
    assert "Analyzed 1 page(s), 1 section(s)" in result.output


def test_migrate_analyze_json_uses_custom_output(runner, tmp_path: Path) -> None:
    artifact_dir = _make_legacy_directory(tmp_path / "crawl")
    output = tmp_path / "reports" / "design.json"

    result = runner.invoke(
        cli,
        [
            "migrate",
            "analyze",
            str(artifact_dir),
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "status": "ok",
        "output": str(output),
        "schema_version": "1.0",
        "pages": 1,
        "sections": 1,
        "warnings": 0,
    }
    assert output.is_file()


def test_migrate_analyze_missing_directory_has_categorized_json_error(
    runner, tmp_path: Path
) -> None:
    missing = tmp_path / "missing"

    result = runner.invoke(
        cli, ["migrate", "analyze", str(missing), "--json"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["category"] == "source_unavailable"
    assert payload["artifact"] == str(missing / "site-inventory.json")
    assert "migrate crawl" in payload["recommended_action"]


def test_migrate_analyze_malformed_inventory_has_schema_error(
    runner, tmp_path: Path
) -> None:
    (tmp_path / "site-inventory.json").write_text("{bad", encoding="utf-8")

    result = runner.invoke(
        cli, ["migrate", "analyze", str(tmp_path), "--json"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["category"] == "schema_invalid"
    assert payload["artifact"] == str(tmp_path / "site-inventory.json")
    assert "Repair or restore" in payload["recommended_action"]
    assert "line 1" in payload["message"]


def test_migrate_analyze_retains_partial_artifacts_with_warning(
    runner, tmp_path: Path
) -> None:
    artifact_dir = _make_legacy_directory(tmp_path, missing_section=True)

    result = runner.invoke(
        cli, ["migrate", "analyze", str(artifact_dir), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["warnings"] == 1
    document = read_design_document(artifact_dir / "design-document.json")
    assert document.pages[0].sections == []
    assert document.warnings[0].code == "legacy_section_unreadable"


@responses.activate
def test_migrate_crawl_adds_design_document_without_removing_legacy_artifacts(
    runner, tmp_path: Path
) -> None:
    _register_site(responses.mock)
    output = tmp_path / "crawl"

    result = runner.invoke(
        cli,
        ["migrate", "crawl", SOURCE_URL, "--output-dir", str(output), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["design_document"] == str(output / "design-document.json")
    assert (output / "design-document.json").is_file()
    assert (output / "site-inventory.json").is_file()
    assert (output / "pages" / "home" / "section-001-hero.json").is_file()
    assert read_design_document(output / "design-document.json").pages


@responses.activate
def test_migrate_crawl_legacy_only_skips_design_document(
    runner, tmp_path: Path
) -> None:
    _register_site(responses.mock)
    output = tmp_path / "crawl"

    result = runner.invoke(
        cli,
        [
            "migrate",
            "crawl",
            SOURCE_URL,
            "--output-dir",
            str(output),
            "--legacy-only",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["design_document"] is None
    assert not (output / "design-document.json").exists()
    assert (output / "site-inventory.json").is_file()
