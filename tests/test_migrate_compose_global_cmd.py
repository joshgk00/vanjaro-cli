"""Tests for vanjaro migrate compose-global."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.commands.migrate_compose_global_cmd import compose_global


def _make_global(tmp_path: Path, element_type: str, content: dict) -> Path:
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


def _write_fake_footer_template(templates_dir: Path) -> None:
    """Minimal Footer (3-column) lookalike with heading and list-item slots."""
    (templates_dir / "Navigation").mkdir(parents=True, exist_ok=True)
    template = {
        "name": "Footer (3-column)",
        "category": "Navigation",
        "description": "Three-column footer",
        "template": {
            "type": "section",
            "attributes": {"id": "tpl-footer-s"},
            "components": [
                {
                    "type": "grid",
                    "attributes": {"id": "tpl-footer-g"},
                    "components": [
                        {
                            "type": "heading",
                            "tagName": "h4",
                            "content": "Column 1",
                            "attributes": {"id": "tpl-footer-h1"},
                        },
                        {
                            "type": "list-item",
                            "content": "Item A",
                            "attributes": {"id": "tpl-footer-li1"},
                        },
                        {
                            "type": "list-item",
                            "content": "Item B",
                            "attributes": {"id": "tpl-footer-li2"},
                        },
                        {
                            "type": "text",
                            "content": "Copyright notice",
                            "attributes": {"id": "tpl-footer-t1"},
                        },
                    ],
                },
            ],
        },
        "styles": [],
    }
    (templates_dir / "Navigation" / "footer-3col.json").write_text(
        json.dumps(template), encoding="utf-8"
    )


def test_compose_global_applies_overrides_from_crawled_content(
    runner, tmp_path: Path, monkeypatch
):
    """Headings, text, list-items from content map to template slots."""
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    source = _make_global(
        tmp_path,
        "footer",
        {
            "headings": ["Quick Links"],
            "paragraphs": ["© 2026 Example Corp. All rights reserved."],
            "list_items": ["Home", "About"],
        },
    )
    output = tmp_path / "footer-composed.json"

    result = runner.invoke(
        compose_global,
        [
            "--source", str(source),
            "--template", "Footer (3-column)",
            "--output", str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["status"] == "composed"
    assert body["template_name"] == "Footer (3-column)"

    composed = json.loads(output.read_text())
    # Walk the composed tree and check contents
    flat_contents: list[str] = []
    def _walk(node):
        if isinstance(node, dict):
            if node.get("content"):
                flat_contents.append(node["content"])
            for child in node.get("components", []):
                _walk(child)
    _walk(composed["template"])

    assert "Quick Links" in flat_contents
    assert "Home" in flat_contents
    assert "About" in flat_contents
    assert "© 2026 Example Corp. All rights reserved." in flat_contents


def test_compose_global_set_pairs_override_derived_values(
    runner, tmp_path: Path, monkeypatch
):
    """Explicit --set values take precedence over values from crawled content."""
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    source = _make_global(
        tmp_path,
        "footer",
        {"headings": ["Crawled Heading"]},
    )
    output = tmp_path / "footer-composed.json"

    runner.invoke(
        compose_global,
        [
            "--source", str(source),
            "--template", "Footer (3-column)",
            "--output", str(output),
            "--set", "heading_1=Forced Heading",
            "--json",
        ],
    )

    composed = json.loads(output.read_text())
    flat_contents: list[str] = []
    def _walk(node):
        if isinstance(node, dict):
            if node.get("content"):
                flat_contents.append(node["content"])
            for child in node.get("components", []):
                _walk(child)
    _walk(composed["template"])

    assert "Forced Heading" in flat_contents
    assert "Crawled Heading" not in flat_contents


def test_compose_global_reports_overflow_for_unusable_overrides(
    runner, tmp_path: Path, monkeypatch
):
    """Overrides with no matching template slot are reported as dropped."""
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    # Crawled footer has images but Footer template has no image slots
    source = _make_global(
        tmp_path,
        "footer",
        {
            "headings": ["Quick Links"],
            "images": [
                {"src": "https://example.com/logo.png", "alt": "Logo"},
            ],
        },
    )
    output = tmp_path / "footer-composed.json"

    result = runner.invoke(
        compose_global,
        [
            "--source", str(source),
            "--template", "Footer (3-column)",
            "--output", str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0
    body = json.loads(result.output)
    assert "image_1_src" in body["dropped_overrides"]
    assert "image_1_alt" in body["dropped_overrides"]
    assert body["overrides_applied"] == 3  # heading_1, image_1_src, image_1_alt all count as applied


def test_compose_global_errors_when_source_missing(runner, tmp_path: Path, monkeypatch):
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    result = runner.invoke(
        compose_global,
        [
            "--source", str(tmp_path / "missing.json"),
            "--template", "Footer (3-column)",
            "--output", str(tmp_path / "out.json"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_compose_global_errors_when_source_has_no_content_block(
    runner, tmp_path: Path, monkeypatch
):
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    malformed = tmp_path / "bad.json"
    malformed.write_text(json.dumps({"type": "footer"}), encoding="utf-8")

    result = runner.invoke(
        compose_global,
        [
            "--source", str(malformed),
            "--template", "Footer (3-column)",
            "--output", str(tmp_path / "out.json"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "content" in result.output.lower()


def test_compose_global_errors_when_template_not_found(
    runner, tmp_path: Path, monkeypatch
):
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    source = _make_global(tmp_path, "footer", {"headings": ["X"]})

    result = runner.invoke(
        compose_global,
        [
            "--source", str(source),
            "--template", "Nonexistent Template",
            "--output", str(tmp_path / "out.json"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_compose_global_rejects_invalid_set_format(
    runner, tmp_path: Path, monkeypatch
):
    templates_dir = tmp_path / "templates"
    _write_fake_footer_template(templates_dir)
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(templates_dir))

    source = _make_global(tmp_path, "footer", {"headings": ["X"]})

    result = runner.invoke(
        compose_global,
        [
            "--source", str(source),
            "--template", "Footer (3-column)",
            "--output", str(tmp_path / "out.json"),
            "--set", "badformat-no-equals",
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "key=value" in result.output.lower() or "invalid" in result.output.lower()
