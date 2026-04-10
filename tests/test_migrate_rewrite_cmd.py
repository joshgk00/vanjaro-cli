"""Tests for vanjaro migrate rewrite-urls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.commands.migrate_rewrite_cmd import rewrite_urls
from vanjaro_cli.migration.url_rewrite import (
    RewriteError,
    build_asset_lookup,
    build_page_lookup,
    rewrite_tree,
)


# -- Helpers --


def _image(src: str, component_id: str = "img1") -> dict:
    return {
        "type": "image",
        "attributes": {"id": component_id, "src": src, "alt": "Photo"},
    }


def _button(href: str, component_id: str = "btn1", label: str = "Click") -> dict:
    return {
        "type": "button",
        "tagName": "a",
        "content": label,
        "attributes": {"id": component_id, "href": href, "role": "button"},
    }


def _section(*children: dict) -> dict:
    return {
        "type": "section",
        "attributes": {"id": "section-1"},
        "components": list(children),
    }


def _write_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _basic_manifest() -> list[dict]:
    return [
        {
            "source_url": "https://example.com/images/hero.jpg",
            "local_file": "hero.jpg",
            "vanjaro_url": "/Portals/0/Images/Migration/hero.jpg",
            "vanjaro_file_id": 42,
            "uploaded": True,
        },
        {
            "source_url": "https://example.com/images/team.jpg",
            "local_file": "team.jpg",
            "vanjaro_url": "/Portals/0/Images/Migration/team.jpg",
            "vanjaro_file_id": 43,
            "uploaded": True,
        },
    ]


def _basic_page_map() -> dict[str, str]:
    return {
        "https://example.com/": "/",
        "https://example.com/about": "/about",
        "https://example.com/services": "/services",
    }


# -- build_asset_lookup --


def test_build_asset_lookup_includes_path_and_absolute_keys():
    lookup = build_asset_lookup(_basic_manifest())
    assert lookup["https://example.com/images/hero.jpg"] == (
        "/Portals/0/Images/Migration/hero.jpg"
    )
    assert lookup["/images/hero.jpg"] == (
        "/Portals/0/Images/Migration/hero.jpg"
    )


def test_build_asset_lookup_skips_unuploaded_entries():
    manifest = _basic_manifest()
    manifest.append({
        "source_url": "https://example.com/images/broken.jpg",
        "vanjaro_url": None,
        "uploaded": False,
    })
    lookup = build_asset_lookup(manifest)
    assert "https://example.com/images/broken.jpg" not in lookup


def test_build_asset_lookup_rejects_non_list():
    with pytest.raises(RewriteError):
        build_asset_lookup({"not": "a list"})  # type: ignore[arg-type]


def test_build_asset_lookup_rejects_non_dict_entry():
    manifest = [{"source_url": "x", "vanjaro_url": "/x"}, "not-a-dict"]
    with pytest.raises(RewriteError, match="#1"):
        build_asset_lookup(manifest)  # type: ignore[list-item]


# -- build_page_lookup --


def test_build_page_lookup_handles_trailing_slash_variants():
    lookup = build_page_lookup({"https://example.com/about/": "/about"})
    assert lookup["https://example.com/about/"] == "/about"
    assert lookup["https://example.com/about"] == "/about"


def test_build_page_lookup_accepts_none():
    assert build_page_lookup(None) == {}


# -- rewrite_tree: images --


def test_rewrite_tree_replaces_image_src():
    content = {
        "components": [
            _section(_image("https://example.com/images/hero.jpg")),
        ],
        "styles": [],
    }

    report = rewrite_tree(content, build_asset_lookup(_basic_manifest()), {})

    rewritten_src = content["components"][0]["components"][0]["attributes"]["src"]
    assert rewritten_src == "/Portals/0/Images/Migration/hero.jpg"
    assert report.images_rewritten == 1
    assert report.images_unchanged == 0


def test_rewrite_tree_tracks_missing_assets():
    content = {
        "components": [_section(_image("https://example.com/images/missing.jpg"))],
    }

    report = rewrite_tree(content, build_asset_lookup(_basic_manifest()), {})

    assert report.images_rewritten == 0
    assert report.unique_missing_assets() == [
        "https://example.com/images/missing.jpg"
    ]


def test_rewrite_tree_dedupes_repeated_missing_assets():
    content = {
        "components": [
            _section(
                _image("https://example.com/images/missing.jpg", component_id="a"),
                _image("https://example.com/images/missing.jpg", component_id="b"),
                _image("https://example.com/images/missing.jpg", component_id="c"),
            ),
        ],
    }

    report = rewrite_tree(content, build_asset_lookup(_basic_manifest()), {})

    assert report.images_unchanged == 3
    assert report.unique_missing_assets() == [
        "https://example.com/images/missing.jpg"
    ]
    assert report.as_dict()["images"]["missing"] == [
        "https://example.com/images/missing.jpg"
    ]


def test_rewrite_tree_resolves_relative_image_via_path_fallback():
    content = {
        "components": [_section(_image("/images/hero.jpg"))],
    }

    report = rewrite_tree(content, build_asset_lookup(_basic_manifest()), {})

    rewritten = content["components"][0]["components"][0]["attributes"]["src"]
    assert rewritten == "/Portals/0/Images/Migration/hero.jpg"
    assert report.images_rewritten == 1


# -- rewrite_tree: links --


def test_rewrite_tree_replaces_internal_link_href():
    content = {
        "components": [_section(_button("https://example.com/about"))],
    }

    report = rewrite_tree(
        content, {}, build_page_lookup(_basic_page_map())
    )

    rewritten_href = content["components"][0]["components"][0]["attributes"]["href"]
    assert rewritten_href == "/about"
    assert report.links_rewritten == 1


def test_rewrite_tree_leaves_anchors_alone():
    content = {
        "components": [_section(_button("#testimonials"))],
    }

    report = rewrite_tree(
        content, {}, build_page_lookup(_basic_page_map())
    )

    href = content["components"][0]["components"][0]["attributes"]["href"]
    assert href == "#testimonials"
    assert report.anchors_skipped == 1
    assert report.links_rewritten == 0


def test_rewrite_tree_leaves_external_absolute_urls_alone():
    content = {
        "components": [_section(_button("https://twitter.com/acme"))],
    }

    report = rewrite_tree(
        content, {}, build_page_lookup(_basic_page_map())
    )

    href = content["components"][0]["components"][0]["attributes"]["href"]
    assert href == "https://twitter.com/acme"
    assert report.external_skipped == 1
    assert report.links_rewritten == 0


def test_rewrite_tree_leaves_mailto_and_tel_alone():
    content = {
        "components": [
            _section(
                _button("mailto:hi@example.com", component_id="btn-mail"),
                _button("tel:+15551234567", component_id="btn-tel"),
            ),
        ],
    }

    report = rewrite_tree(
        content, {}, build_page_lookup(_basic_page_map())
    )

    children = content["components"][0]["components"]
    assert children[0]["attributes"]["href"] == "mailto:hi@example.com"
    assert children[1]["attributes"]["href"] == "tel:+15551234567"
    assert report.links_rewritten == 0


def test_rewrite_tree_relative_link_already_at_target_is_unchanged():
    # Page map value is "/about" and the component already uses "/about" —
    # path-only fallback resolves to the same value, so it counts as
    # unchanged rather than rewritten.
    content = {
        "components": [_section(_button("/about"))],
    }

    report = rewrite_tree(
        content, {}, build_page_lookup(_basic_page_map())
    )

    href = content["components"][0]["components"][0]["attributes"]["href"]
    assert href == "/about"
    assert report.links_unchanged == 1
    assert report.links_rewritten == 0


def test_rewrite_tree_passes_through_library_plan_vanjaro_paths():
    """Regression: library plan hard-codes `/contact` that is ONLY a target value.

    The source crawl had no `/contact` page (the source site used an anchor
    `#contact` on the home page). A Stage 2 library plan author wrote
    ``button_1_href: "/contact"`` anyway because they knew a Vanjaro
    ``/Contact`` page would be created in Stage 4. The rewriter used to flag
    this as ``missing`` because the path didn't exist as a key anywhere in
    the page map — only as a value. Fix: `build_page_lookup` now injects
    identity mappings for every distinct target so the href passes through
    as ``links_unchanged`` with no missing report entry.
    """
    page_map = {
        "https://example.com/": "/",
        "https://example.com/about": "/about",
        # No entry whose source matches anything producing "/contact" —
        # "/contact" appears only as a target value via the hand-written
        # entry below:
        "https://example.com/#contact": "/contact",
    }
    content = {
        "components": [_section(_button("/contact"))],
    }

    report = rewrite_tree(content, {}, build_page_lookup(page_map))

    href = content["components"][0]["components"][0]["attributes"]["href"]
    assert href == "/contact"
    assert report.links_unchanged == 1
    assert report.links_rewritten == 0
    assert report.unique_missing_pages() == []


def test_build_page_lookup_injects_target_identity_mappings():
    """build_page_lookup should expose target paths as identity keys."""
    page_map = {
        "https://example.com/": "/",
        "https://example.com/#about": "/About",
        "https://example.com/#services": "/Services",
    }

    lookup = build_page_lookup(page_map)

    assert lookup["/About"] == "/About"
    assert lookup["/Services"] == "/Services"
    assert lookup["/"] == "/"


def test_rewrite_tree_accepts_single_section_dict():
    # Callers may pass a raw section dict without wrapping in {"components": [...]}.
    section = _section(
        _image("https://example.com/images/hero.jpg"),
        _button("https://example.com/about"),
    )

    report = rewrite_tree(
        section,
        build_asset_lookup(_basic_manifest()),
        build_page_lookup(_basic_page_map()),
    )

    assert section["components"][0]["attributes"]["src"] == (
        "/Portals/0/Images/Migration/hero.jpg"
    )
    assert section["components"][1]["attributes"]["href"] == "/about"
    assert report.images_rewritten == 1
    assert report.links_rewritten == 1


def test_rewrite_tree_handles_empty_components_array():
    content = {"components": [], "styles": []}

    report = rewrite_tree(content, {}, {})

    assert report.images_rewritten == 0
    assert report.links_rewritten == 0
    assert report.as_dict()["images"]["missing"] == []


def test_rewrite_tree_rejects_non_dict_content():
    with pytest.raises(RewriteError):
        rewrite_tree([], {}, {})  # type: ignore[arg-type]


# -- CLI: full file rewrite --


def test_cli_rewrites_content_file_in_place(runner, tmp_path):
    manifest = _basic_manifest()
    page_map = _basic_page_map()
    content = {
        "components": [
            _section(
                _image("https://example.com/images/hero.jpg"),
                _button("https://example.com/about"),
            ),
        ],
        "styles": [],
    }

    content_file = _write_json(tmp_path / "page.json", content)
    manifest_file = _write_json(tmp_path / "manifest.json", manifest)
    page_map_file = _write_json(tmp_path / "page-map.json", page_map)

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
            "--page-map", str(page_map_file),
        ],
    )

    assert result.exit_code == 0, result.output
    written = json.loads(content_file.read_text())
    section = written["components"][0]
    assert section["components"][0]["attributes"]["src"] == (
        "/Portals/0/Images/Migration/hero.jpg"
    )
    assert section["components"][1]["attributes"]["href"] == "/about"


def test_cli_writes_to_separate_output_file(runner, tmp_path):
    content = {
        "components": [_section(_image("https://example.com/images/hero.jpg"))]
    }
    content_file = _write_json(tmp_path / "page.json", content)
    manifest_file = _write_json(tmp_path / "manifest.json", _basic_manifest())
    output_file = tmp_path / "rewritten.json"

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
            "--output", str(output_file),
        ],
    )

    assert result.exit_code == 0, result.output
    original = json.loads(content_file.read_text())
    assert original["components"][0]["components"][0]["attributes"]["src"] == (
        "https://example.com/images/hero.jpg"
    )
    rewritten = json.loads(output_file.read_text())
    assert rewritten["components"][0]["components"][0]["attributes"]["src"] == (
        "/Portals/0/Images/Migration/hero.jpg"
    )


def test_cli_json_output_includes_report(runner, tmp_path):
    content = {
        "components": [
            _section(
                _image("https://example.com/images/hero.jpg"),
                _button("https://example.com/about"),
                _button("#anchor"),
            ),
        ],
    }
    content_file = _write_json(tmp_path / "page.json", content)
    manifest_file = _write_json(tmp_path / "manifest.json", _basic_manifest())
    page_map_file = _write_json(tmp_path / "page-map.json", _basic_page_map())

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
            "--page-map", str(page_map_file),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["report"]["images"]["rewritten"] == 1
    assert payload["report"]["links"]["rewritten"] == 1
    assert payload["report"]["links"]["anchors"] == 1


def test_cli_report_flag_prints_summary(runner, tmp_path):
    content = {
        "components": [_section(_image("https://example.com/images/hero.jpg"))]
    }
    content_file = _write_json(tmp_path / "page.json", content)
    manifest_file = _write_json(tmp_path / "manifest.json", _basic_manifest())

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
            "--report",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "images:" in result.output
    assert "links:" in result.output


def test_cli_missing_content_file_errors(runner, tmp_path):
    manifest_file = _write_json(tmp_path / "manifest.json", _basic_manifest())

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(tmp_path / "nope.json"),
            "--asset-manifest", str(manifest_file),
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_cli_without_page_map_rewrites_only_images(runner, tmp_path):
    content = {
        "components": [
            _section(
                _image("https://example.com/images/hero.jpg"),
                _button("https://example.com/about"),
            ),
        ],
    }
    content_file = _write_json(tmp_path / "page.json", content)
    manifest_file = _write_json(tmp_path / "manifest.json", _basic_manifest())

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
        ],
    )

    assert result.exit_code == 0, result.output
    written = json.loads(content_file.read_text())
    section = written["components"][0]
    assert section["components"][0]["attributes"]["src"] == (
        "/Portals/0/Images/Migration/hero.jpg"
    )
    assert section["components"][1]["attributes"]["href"] == (
        "https://example.com/about"
    )


def test_cli_manifest_not_a_list_errors_with_file_path(runner, tmp_path):
    content_file = _write_json(tmp_path / "page.json", {"components": []})
    manifest_file = _write_json(tmp_path / "manifest.json", {"not": "a list"})

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
        ],
    )

    assert result.exit_code != 0
    assert "manifest.json" in result.output
    assert "JSON array" in result.output


def test_cli_invalid_json_reports_clear_error(runner, tmp_path):
    content_file = tmp_path / "page.json"
    content_file.write_text("{not valid json")
    manifest_file = _write_json(tmp_path / "manifest.json", _basic_manifest())

    result = runner.invoke(
        rewrite_urls,
        [
            "--content", str(content_file),
            "--asset-manifest", str(manifest_file),
        ],
    )

    assert result.exit_code != 0
    assert "Invalid JSON" in result.output
