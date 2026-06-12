"""Tests for vanjaro migrate build-global."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.commands.migrate_build_global_cmd import build_global
from vanjaro_cli.migration.global_blocks import MENU_BLOCK_GUID


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


def _find_all_in_tree(tree: dict, predicate) -> list[dict]:
    result: list[dict] = []
    def _walk(node):
        if not isinstance(node, dict):
            return
        if predicate(node):
            result.append(node)
        for child in node.get("components", []) or []:
            _walk(child)
    _walk(tree)
    return result


def test_build_global_header_default_embeds_menu_block(runner, tmp_path: Path):
    """Default header build (no --static-nav) includes the Vanjaro Menu blockwrapper."""
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
        ["--source", str(source), "--kind", "header", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    written = json.loads(output.read_text())
    section = written["components"][0]
    menu_nodes = _find_all_in_tree(section, lambda n: n.get("type") == "blockwrapper")
    assert len(menu_nodes) == 1
    assert menu_nodes[0]["attributes"]["data-block-guid"] == MENU_BLOCK_GUID
    assert menu_nodes[0]["attributes"]["data-block-type"] == "Menu"


def test_build_global_header_static_nav_embeds_crawled_items(runner, tmp_path: Path):
    """--static-nav embeds the crawled nav entries instead of the live Menu block."""
    source = _make_global(
        tmp_path,
        "header",
        {
            "images": [{"src": "/logo.png", "alt": "Logo"}],
            "nav_items": [{"label": "Home", "href": "/"}, {"label": "About", "href": "/about"}],
        },
    )
    output = tmp_path / "header-static.json"

    result = runner.invoke(
        build_global,
        ["--source", str(source), "--kind", "header", "--output", str(output), "--static-nav"],
    )

    assert result.exit_code == 0, result.output
    written = json.loads(output.read_text())
    section = written["components"][0]
    menu_nodes = _find_all_in_tree(section, lambda n: n.get("type") == "blockwrapper")
    assert len(menu_nodes) == 0

    def _collect_content(node):
        result = []
        if not isinstance(node, dict):
            return result
        if isinstance(node.get("content"), str) and node["content"]:
            result.append(node["content"])
        for child in node.get("components", []) or []:
            result.extend(_collect_content(child))
        return result

    contents = _collect_content(section)
    assert "Home" in contents
    assert "About" in contents


def test_build_global_theme_palette_maps_footer_band_to_class(runner, tmp_path: Path, write_json):
    source = _make_global(
        tmp_path,
        "footer",
        {
            "headings": ["Links"],
            "list_items": ["About"],
            "background_color": "#343a40",
        },
    )
    palette = write_json(tmp_path / "palette.json", {"dark": "#343a40", "light": "#f8f9fa"})
    output = tmp_path / "footer-built.json"

    result = runner.invoke(
        build_global,
        [
            "--source", str(source),
            "--kind", "footer",
            "--output", str(output),
            "--theme-palette", str(palette),
        ],
    )

    assert result.exit_code == 0, result.output
    section = json.loads(output.read_text())["components"][0]
    class_names = [c["name"] for c in section.get("classes", [])]
    assert "bg-dark" in class_names
    assert "text-light" in class_names
    assert "style" not in section["attributes"]


def test_build_global_theme_palette_unmatched_color_lands_in_styles(runner, tmp_path: Path, write_json):
    source = _make_global(
        tmp_path,
        "header",
        {
            "images": [{"src": "/logo.png", "alt": "Logo"}],
            "background_color": "#7b1fa2",
        },
    )
    palette = write_json(tmp_path / "palette.json", {"primary": "#00aa55"})
    output = tmp_path / "header-built.json"

    result = runner.invoke(
        build_global,
        [
            "--source", str(source),
            "--kind", "header",
            "--output", str(output),
            "--theme-palette", str(palette),
        ],
    )

    assert result.exit_code == 0, result.output
    built = json.loads(output.read_text())
    section = built["components"][0]
    section_id = section["attributes"]["id"]
    assert "style" not in section["attributes"]
    def _targets(rule: dict) -> bool:
        first = (rule.get("selectors") or [None])[0]
        return isinstance(first, dict) and first.get("name") == section_id

    band_rules = [rule for rule in built["styles"] if _targets(rule)]
    assert band_rules
    assert band_rules[0]["style"]["background-color"] == "#7b1fa2"
