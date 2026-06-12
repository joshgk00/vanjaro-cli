"""Tests for cross-page section dedup and the migrate dedup-sections command."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.commands.migrate_dedup_cmd import dedup_sections
from vanjaro_cli.migration.dedup import (
    find_duplicate_groups,
    humanize_key,
    normalize_section,
    section_fingerprint,
)


def _cta_section(button_href: str = "/signup", ver: str = "abc") -> dict:
    return {
        "type": "cta",
        "template": "CTA Strip",
        "content": {
            "headings": ["Get Started Today"],
            "paragraphs": ["Sign up now and save."],
            "images": [{"src": f"https://x.com/cta.png?ver={ver}", "alt": "CTA"}],
            "buttons": [{"text": "Sign Up", "href": button_href}],
            "background_color": "#ff0000",
            "text_color": "#ffffff",
        },
    }


def _write_section(pages_dir: Path, page: str, filename: str, section: dict) -> Path:
    page_dir = pages_dir / page
    page_dir.mkdir(parents=True, exist_ok=True)
    path = page_dir / filename
    path.write_text(json.dumps(section), encoding="utf-8")
    return path


# -- normalize_section --


def test_normalize_strips_image_query_strings():
    section = {
        "type": "hero",
        "template": "Hero",
        "content": {"images": [{"src": "https://x.com/a.png?ver=123&w=400", "alt": "A"}]},
    }

    normalized = normalize_section(section)

    assert normalized["images"] == [{"src": "https://x.com/a.png", "alt": "A"}]


def test_normalize_strips_link_query_but_keeps_path():
    section = {
        "type": "cta",
        "template": "CTA",
        "content": {"buttons": [{"text": "Go", "href": "/signup?ref=home"}]},
    }

    normalized = normalize_section(section)

    assert normalized["buttons"] == [{"text": "Go", "href": "/signup"}]


def test_normalize_excludes_colors_and_background_image():
    with_colors = {
        "type": "cta",
        "template": "CTA",
        "content": {
            "headings": ["Hi"],
            "background_color": "#000",
            "text_color": "#fff",
            "background_image": "https://x.com/bg.jpg",
        },
    }
    without_colors = {
        "type": "cta",
        "template": "CTA",
        "content": {"headings": ["Hi"]},
    }

    assert section_fingerprint(with_colors) == section_fingerprint(without_colors)


def test_normalize_drops_srcset_noise():
    section = {
        "type": "hero",
        "template": "Hero",
        "content": {
            "images": [{
                "src": "https://x.com/a.png",
                "alt": "A",
                "srcset": "a-400.png 400w, a-800.png 800w",
                "picture_source": ["a.webp"],
            }],
        },
    }

    normalized = normalize_section(section)

    assert normalized["images"] == [{"src": "https://x.com/a.png", "alt": "A"}]


# -- section_fingerprint --


def test_fingerprint_is_stable_across_query_string_jitter():
    assert section_fingerprint(_cta_section(ver="abc")) == section_fingerprint(
        _cta_section(ver="zzz")
    )


def test_fingerprint_differs_on_different_link_target():
    assert section_fingerprint(_cta_section(button_href="/signup")) != section_fingerprint(
        _cta_section(button_href="/contact")
    )


# -- find_duplicate_groups --


def test_groups_section_repeated_across_two_pages(tmp_path):
    pages_dir = tmp_path / "pages"
    _write_section(pages_dir, "home", "section-003-cta.json", _cta_section())
    _write_section(pages_dir, "about", "section-002-cta.json", _cta_section())

    groups = find_duplicate_groups(pages_dir)

    assert len(groups) == 1
    group = groups[0]
    assert group.key == "global-cta-get-started-today"
    assert group.pages == ["about", "home"]
    assert len(group.member_files) == 2


def test_same_page_repeat_is_not_a_duplicate_group(tmp_path):
    pages_dir = tmp_path / "pages"
    _write_section(pages_dir, "home", "section-001-cta.json", _cta_section())
    _write_section(pages_dir, "home", "section-009-cta.json", _cta_section())

    groups = find_duplicate_groups(pages_dir)

    assert groups == []


def test_unique_sections_produce_no_groups(tmp_path):
    pages_dir = tmp_path / "pages"
    _write_section(pages_dir, "home", "section-001-cta.json", _cta_section(button_href="/a"))
    _write_section(pages_dir, "about", "section-001-cta.json", _cta_section(button_href="/b"))

    assert find_duplicate_groups(pages_dir) == []


def test_humanize_key():
    assert humanize_key("global-cta-get-started") == "Global Cta Get Started"


# -- dedup-sections command --


def test_dry_run_prints_groups_without_writing(runner, tmp_path):
    pages_dir = tmp_path / "pages"
    home = _write_section(pages_dir, "home", "section-001-cta.json", _cta_section())
    _write_section(pages_dir, "about", "section-001-cta.json", _cta_section())

    result = runner.invoke(dedup_sections, [str(tmp_path), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "global-cta-get-started-today" in result.output
    # Source file untouched in dry-run.
    assert json.loads(home.read_text())["type"] == "cta"
    assert not (tmp_path / "global-sections-plan.json").exists()


def test_default_run_writes_plan_and_rewrites_stubs(runner, tmp_path):
    pages_dir = tmp_path / "pages"
    home = _write_section(pages_dir, "home", "section-001-cta.json", _cta_section())
    about = _write_section(pages_dir, "about", "section-001-cta.json", _cta_section())

    result = runner.invoke(dedup_sections, [str(tmp_path)])

    assert result.exit_code == 0, result.output

    plan = json.loads((tmp_path / "global-sections-plan.json").read_text())
    assert len(plan) == 1
    entry = plan[0]
    assert entry["type"] == "global"
    assert entry["category"] == "Global Sections"
    assert entry["template"] == "CTA Strip"
    assert entry["key"] == "global-cta-get-started-today"
    assert entry["name"] == "Global Cta Get Started Today"
    assert entry["overrides"]["heading_1"] == "Get Started Today"

    for member in (home, about):
        stub = json.loads(member.read_text())
        assert stub["global_key"] == "global-cta-get-started-today"
        assert stub["original_backup"]["type"] == "cta"
        wrapper = stub["components"][0]
        assert wrapper["type"] == "globalblockwrapper"
        assert wrapper["attributes"]["data-guid"] == "{{global:global-cta-get-started-today}}"


def test_default_run_with_no_duplicates_reports_nothing(runner, tmp_path):
    pages_dir = tmp_path / "pages"
    _write_section(pages_dir, "home", "section-001-cta.json", _cta_section(button_href="/a"))
    _write_section(pages_dir, "about", "section-001-cta.json", _cta_section(button_href="/b"))

    result = runner.invoke(dedup_sections, [str(tmp_path), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["groups"] == []
    assert not (tmp_path / "global-sections-plan.json").exists()


def test_dedup_errors_without_pages_dir(runner, tmp_path):
    result = runner.invoke(dedup_sections, [str(tmp_path)])

    assert result.exit_code != 0
    assert "pages/" in result.output
