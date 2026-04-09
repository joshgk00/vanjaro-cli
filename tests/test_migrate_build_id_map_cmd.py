"""Tests for vanjaro migrate build-id-map."""

from __future__ import annotations

import json
from pathlib import Path

import responses

from vanjaro_cli.cli import cli
from vanjaro_cli.commands.migrate_build_id_map_cmd import (
    _build_vanjaro_index,
    _match_inventory_to_vanjaro,
    _normalize_name,
    _normalize_path,
)
from vanjaro_cli.models.page import Page
from tests.conftest import BASE_URL, mock_homepage

LIST_AI_PAGES_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/List"


# -- Helpers --


def _make_vanjaro_page(
    page_id: int,
    name: str,
    path: str,
    *,
    is_portal_home: bool = False,
    title: str | None = None,
) -> Page:
    return Page.from_api({
        "tabId": page_id,
        "name": name,
        "title": title or name,
        "url": path,
        "isPortalHome": is_portal_home,
        "hasVanjaroContent": True,
    })


def _write_inventory(tmp_path: Path, pages: list[dict]) -> Path:
    inventory = {
        "source_url": "https://example.com",
        "crawled_at": "2026-04-09T00:00:00+00:00",
        "pages": pages,
        "assets": {"count": 0, "manifest": "assets/manifest.json"},
        "global": {},
    }
    inventory_path = tmp_path / "site-inventory.json"
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    return inventory_path


def _make_source_page(
    url: str, path: str, title: str, slug: str
) -> dict:
    return {
        "url": url,
        "path": path,
        "title": title,
        "slug": slug,
        "sections": [],
    }


# -- _normalize_* --


def test_normalize_path_lowercases_and_strips_trailing_slash():
    assert _normalize_path("/About-Us/") == "/about-us"
    assert _normalize_path("/") == "/"
    assert _normalize_path("") == ""


def test_normalize_name_collapses_whitespace_and_lowercases():
    assert _normalize_name("  About   Us  ") == "about us"
    assert _normalize_name("") == ""


# -- _build_vanjaro_index --


def test_build_vanjaro_index_captures_portal_home():
    pages = [
        _make_vanjaro_page(10, "Home", "/", is_portal_home=True),
        _make_vanjaro_page(11, "About", "/About"),
    ]
    index = _build_vanjaro_index(pages)

    assert index["portal_home_id"] == 10
    assert index["by_path"]["/"] == 10
    assert index["by_path"]["/about"] == 11
    assert index["by_name"]["about"] == 11


def test_build_vanjaro_index_first_wins_on_collisions():
    pages = [
        _make_vanjaro_page(10, "About", "/about"),
        _make_vanjaro_page(11, "About", "/about-legacy"),
    ]
    index = _build_vanjaro_index(pages)

    assert index["by_name"]["about"] == 10


# -- _match_inventory_to_vanjaro --


def test_match_exact_path_hit():
    inventory = {
        "pages": [
            _make_source_page(
                "https://example.com/about", "/about", "About Us", "about"
            )
        ]
    }
    index = _build_vanjaro_index([_make_vanjaro_page(42, "About", "/About")])

    mapping, unmatched = _match_inventory_to_vanjaro(inventory, index)

    assert mapping == {"https://example.com/about": 42}
    assert unmatched == []


def test_match_portal_home_fallback():
    inventory = {
        "pages": [
            _make_source_page("https://example.com/", "/", "Home", "home")
        ]
    }
    # Vanjaro home lives at a different path (e.g., /Home) but is flagged
    # isPortalHome, so the matcher should still find it.
    index = _build_vanjaro_index([
        _make_vanjaro_page(5, "Landing", "/Landing", is_portal_home=True)
    ])

    mapping, unmatched = _match_inventory_to_vanjaro(inventory, index)

    assert mapping == {"https://example.com/": 5}
    assert unmatched == []


def test_match_title_fallback_when_path_misses():
    inventory = {
        "pages": [
            _make_source_page(
                "https://example.com/our-story",
                "/our-story",
                "Our Story",
                "our-story",
            )
        ]
    }
    index = _build_vanjaro_index([
        _make_vanjaro_page(77, "Our Story", "/Company/Our-Story")
    ])

    mapping, unmatched = _match_inventory_to_vanjaro(inventory, index)

    assert mapping == {"https://example.com/our-story": 77}


def test_match_slug_fallback_with_dashes():
    inventory = {
        "pages": [
            _make_source_page(
                "https://example.com/contact-us",
                "/weird-path-xyz",  # path won't match
                "",  # no title
                "contact-us",  # slug with dashes
            )
        ]
    }
    index = _build_vanjaro_index([
        _make_vanjaro_page(88, "Contact Us", "/Support")
    ])

    mapping, unmatched = _match_inventory_to_vanjaro(inventory, index)

    assert mapping == {"https://example.com/contact-us": 88}


def test_match_reports_unmatched_pages():
    inventory = {
        "pages": [
            _make_source_page(
                "https://example.com/ghost", "/ghost", "Ghost Page", "ghost"
            )
        ]
    }
    index = _build_vanjaro_index([
        _make_vanjaro_page(1, "Home", "/", is_portal_home=True)
    ])

    mapping, unmatched = _match_inventory_to_vanjaro(inventory, index)

    assert mapping == {}
    assert unmatched == ["https://example.com/ghost"]


# -- CLI --


@responses.activate
def test_cli_happy_path(runner, mock_config, tmp_path):
    mock_homepage()
    inventory_path = _write_inventory(
        tmp_path,
        [
            _make_source_page("https://example.com/", "/", "Home", "home"),
            _make_source_page(
                "https://example.com/about", "/about", "About Us", "about"
            ),
        ],
    )
    output_file = tmp_path / "page-id-map.json"

    responses.add(
        responses.GET,
        LIST_AI_PAGES_URL,
        json={
            "total": 2,
            "pages": [
                {
                    "tabId": 10,
                    "name": "Home",
                    "title": "Home",
                    "path": "/",
                    "isPortalHome": True,
                    "hasVanjaroContent": True,
                },
                {
                    "tabId": 11,
                    "name": "About Us",
                    "title": "About Us",
                    "path": "/About-Us",
                    "hasVanjaroContent": True,
                },
            ],
        },
        status=200,
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "build-id-map",
            "--inventory", str(inventory_path),
            "--output", str(output_file),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["matched"] == 2
    assert payload["unmatched"] == []

    written = json.loads(output_file.read_text())
    assert written == {
        "https://example.com/": 10,
        "https://example.com/about": 11,
    }


@responses.activate
def test_cli_reports_unmatched_in_json_output(runner, mock_config, tmp_path):
    mock_homepage()
    inventory_path = _write_inventory(
        tmp_path,
        [
            _make_source_page("https://example.com/", "/", "Home", "home"),
            _make_source_page(
                "https://example.com/ghost", "/ghost", "Ghost", "ghost"
            ),
        ],
    )
    output_file = tmp_path / "page-id-map.json"

    responses.add(
        responses.GET,
        LIST_AI_PAGES_URL,
        json={
            "total": 1,
            "pages": [
                {
                    "tabId": 10,
                    "name": "Home",
                    "title": "Home",
                    "path": "/",
                    "isPortalHome": True,
                }
            ],
        },
        status=200,
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "build-id-map",
            "--inventory", str(inventory_path),
            "--output", str(output_file),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["matched"] == 1
    assert payload["unmatched"] == ["https://example.com/ghost"]

    written = json.loads(output_file.read_text())
    assert written == {"https://example.com/": 10}


@responses.activate
def test_cli_missing_inventory_errors(runner, mock_config, tmp_path):
    mock_homepage()

    result = runner.invoke(
        cli,
        [
            "migrate", "build-id-map",
            "--inventory", str(tmp_path / "missing.json"),
            "--output", str(tmp_path / "out.json"),
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


@responses.activate
def test_cli_api_error_surfaces_cleanly(runner, mock_config, tmp_path):
    mock_homepage()
    inventory_path = _write_inventory(
        tmp_path,
        [_make_source_page("https://example.com/", "/", "Home", "home")],
    )
    responses.add(
        responses.GET,
        LIST_AI_PAGES_URL,
        json={"Message": "Server down"},
        status=500,
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "build-id-map",
            "--inventory", str(inventory_path),
            "--output", str(tmp_path / "out.json"),
        ],
    )

    assert result.exit_code != 0
    assert "vanjaro pages" in result.output.lower() or "500" in result.output
