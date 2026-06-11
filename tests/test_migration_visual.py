"""Tests for migration.visual capture planning and the visual-capture command."""

from __future__ import annotations

import json

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.migration.visual import (
    VisualCaptureError,
    build_capture_plan,
    parse_viewport,
    slug_for_path,
)

VANJARO_BASE = "http://vanjarocli.local"


def make_page_map() -> dict[str, str]:
    return {
        "https://source.example/": "/",
        "https://source.example/#about": "/About",
        "https://source.example/about.html": "/About",
        "https://source.example/blog.html": "/Blog",
    }


# ---------------------------------------------------------------------------
# parse_viewport
# ---------------------------------------------------------------------------


def test_parse_viewport_valid():
    assert parse_viewport("1280x800") == (1280, 800)
    assert parse_viewport("375X812") == (375, 812)


@pytest.mark.parametrize("bad", ["1280", "wide x tall", "0x800", "-1x10", ""])
def test_parse_viewport_invalid(bad):
    with pytest.raises(VisualCaptureError, match="viewport|Viewport"):
        parse_viewport(bad)


# ---------------------------------------------------------------------------
# slug_for_path
# ---------------------------------------------------------------------------


def test_slug_for_path_root_is_home():
    assert slug_for_path("/") == "home"


def test_slug_for_path_nested():
    assert slug_for_path("/Blog/Post-One") == "blog-post-one"


# ---------------------------------------------------------------------------
# build_capture_plan
# ---------------------------------------------------------------------------


def test_plan_dedupes_by_vanjaro_path():
    plan = build_capture_plan(make_page_map(), VANJARO_BASE)
    paths = [entry["vanjaro_path"] for entry in plan]
    assert paths == ["/", "/About", "/Blog"]


def test_plan_prefers_fragment_free_source_url():
    plan = build_capture_plan(make_page_map(), VANJARO_BASE)
    about = next(entry for entry in plan if entry["vanjaro_path"] == "/About")
    assert about["source_url"] == "https://source.example/about.html"
    assert about["source_fragment"] == ""


def test_plan_keeps_fragment_when_only_source():
    page_map = {"https://source.example/#contact": "/Contact"}
    plan = build_capture_plan(page_map, VANJARO_BASE)
    assert plan[0]["source_url"] == "https://source.example/"
    assert plan[0]["source_fragment"] == "contact"


def test_plan_builds_vanjaro_urls():
    plan = build_capture_plan(make_page_map(), VANJARO_BASE)
    home = next(entry for entry in plan if entry["vanjaro_path"] == "/")
    blog = next(entry for entry in plan if entry["vanjaro_path"] == "/Blog")
    assert home["vanjaro_url"] == f"{VANJARO_BASE}/"
    assert blog["vanjaro_url"] == f"{VANJARO_BASE}/Blog"


def test_plan_include_paths_filter():
    plan = build_capture_plan(make_page_map(), VANJARO_BASE, include_paths=["/Blog"])
    assert len(plan) == 1
    assert plan[0]["vanjaro_path"] == "/Blog"


def test_plan_empty_map():
    assert build_capture_plan({}, VANJARO_BASE) == []


# ---------------------------------------------------------------------------
# visual-capture command validation
# ---------------------------------------------------------------------------


def test_visual_capture_requires_dir_or_page_map(runner, mock_config):
    result = runner.invoke(cli, ["migrate", "visual-capture", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "Provide --dir or --page-map" in data["message"]


def test_visual_capture_missing_map_file(runner, mock_config, tmp_path):
    result = runner.invoke(
        cli, ["migrate", "visual-capture", "--dir", str(tmp_path), "--json"]
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "Page URL map not found" in data["message"]


def test_visual_capture_invalid_viewport(runner, mock_config, tmp_path):
    (tmp_path / "page-url-map.json").write_text(json.dumps(make_page_map()))
    result = runner.invoke(
        cli,
        ["migrate", "visual-capture", "--dir", str(tmp_path), "--viewport", "huge", "--json"],
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "viewport" in data["message"].lower()


def test_visual_capture_empty_after_filter(runner, mock_config, tmp_path):
    (tmp_path / "page-url-map.json").write_text(json.dumps(make_page_map()))
    result = runner.invoke(
        cli,
        [
            "migrate", "visual-capture", "--dir", str(tmp_path),
            "--pages", "/Nonexistent", "--json",
        ],
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "No pages to capture" in data["message"]


def test_visual_capture_runs_plan(runner, mock_config, tmp_path, monkeypatch):
    """Command wires plan + config into run_capture and reports the manifest."""
    (tmp_path / "page-url-map.json").write_text(json.dumps(make_page_map()))
    captured_kwargs = {}

    def fake_run_capture(plan, output_dir, viewport, **kwargs):
        captured_kwargs.update(
            {"plan": plan, "output_dir": output_dir, "viewport": viewport, **kwargs}
        )
        return {
            "viewport": "1280x800",
            "vanjaro_base_url": kwargs["vanjaro_base_url"],
            "pages": [
                {"slug": "home", "warnings": []},
                {"slug": "about", "warnings": ["HTTP 404"]},
            ],
            "warnings": [],
        }

    monkeypatch.setattr(
        "vanjaro_cli.commands.migrate_visual_cmd.run_capture", fake_run_capture
    )
    result = runner.invoke(
        cli, ["migrate", "visual-capture", "--dir", str(tmp_path), "--json"]
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "captured"
    assert data["page_count"] == 2
    assert data["pages_with_warnings"] == ["about"]
    assert len(captured_kwargs["plan"]) == 3
    assert captured_kwargs["viewport"] == (1280, 800)
    # Anonymous by default — admin chrome must not leak into screenshots
    assert captured_kwargs["cookies"] is None
    assert str(captured_kwargs["output_dir"]).endswith("visual-report")
