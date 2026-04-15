"""Tests for vanjaro migrate build-global."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.commands.migrate_build_global_cmd import build_global


def _make_global(tmp_path: Path, element_type: str, content: dict) -> Path:
    """Write a minimal crawled global file and return the path."""
    path = tmp_path / "global" / f"{element_type}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "type": element_type,
            "template": f"Site {element_type.title()}",
            "content": content,
        }),
        encoding="utf-8",
    )
    return path


def test_build_global_writes_components_and_styles_for_header(runner, tmp_path: Path):
    source = _make_global(
        tmp_path,
        "header",
        {
            "images": [{"src": "/logo.png", "alt": "Logo"}],
            "nav_items": [{"label": "Home", "href": "/"}],
        },
    )
    output = tmp_path / "header-built.json"

    result = runner.invoke(
        build_global,
        [
            "--source", str(source),
            "--kind", "header",
            "--output", str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["status"] == "built"
    assert body["kind"] == "header"

    written = json.loads(output.read_text())
    assert "components" in written
    assert "styles" in written
    assert len(written["components"]) == 1
    assert written["components"][0]["type"] == "section"


def test_build_global_writes_footer_with_columns(runner, tmp_path: Path):
    source = _make_global(
        tmp_path,
        "footer",
        {
            "headings": ["Quick Links", "Contact"],
            "list_items": ["About", "Services", "Email", "Phone"],
            "paragraphs": ["© 2026 Example Corp"],
        },
    )
    output = tmp_path / "footer-built.json"

    result = runner.invoke(
        build_global,
        [
            "--source", str(source),
            "--kind", "footer",
            "--output", str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    written = json.loads(output.read_text())
    # Footer has N heading columns, so the top row has multiple columns
    section = written["components"][0]
    container = section["components"][0]
    # Expect columns row first; optionally an about row after
    top_row = container["components"][0]
    columns = [c for c in top_row["components"] if c.get("type") == "column"]
    assert len(columns) == 2  # matches 2 headings


def test_build_global_errors_when_source_missing(runner, tmp_path: Path):
    result = runner.invoke(
        build_global,
        [
            "--source", str(tmp_path / "missing.json"),
            "--kind", "header",
            "--output", str(tmp_path / "out.json"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_build_global_errors_when_content_block_missing(runner, tmp_path: Path):
    malformed = tmp_path / "bad.json"
    malformed.write_text(json.dumps({"type": "header"}), encoding="utf-8")

    result = runner.invoke(
        build_global,
        [
            "--source", str(malformed),
            "--kind", "header",
            "--output", str(tmp_path / "out.json"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "content" in result.output.lower()


def test_build_global_errors_on_invalid_kind(runner, tmp_path: Path):
    source = _make_global(tmp_path, "header", {"list_items": ["x"]})
    result = runner.invoke(
        build_global,
        [
            "--source", str(source),
            "--kind", "sidebar",
            "--output", str(tmp_path / "out.json"),
        ],
    )

    assert result.exit_code != 0
    assert "sidebar" in result.output.lower() or "invalid" in result.output.lower()


def test_build_global_creates_output_directory_if_missing(runner, tmp_path: Path):
    source = _make_global(tmp_path, "header", {"list_items": ["Home"]})
    output = tmp_path / "nested" / "deeply" / "header.json"

    result = runner.invoke(
        build_global,
        [
            "--source", str(source),
            "--kind", "header",
            "--output", str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
