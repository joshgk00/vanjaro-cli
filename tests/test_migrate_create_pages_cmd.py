"""Tests for vanjaro migrate create-pages.

Covers topological ordering, parent-id propagation, includeInMenu based on
header nav_items, dry-run mode, orphan handling, and page-id-map output.
HTTP is mocked with the ``responses`` library at the DNN API boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import responses

from vanjaro_cli.cli import cli
from vanjaro_cli.commands.migrate_create_pages_cmd import _topological_sort
from tests.conftest import BASE_URL, mock_homepage

CREATE_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Create"


# --- Helpers ---


def _inventory_page(
    url_path: str,
    slug: str,
    title: str | None = None,
    parent_slug: str | None = None,
) -> dict:
    return {
        "url": f"https://source.example.com{url_path}",
        "path": url_path,
        "title": title or slug.title(),
        "slug": slug,
        "parent_slug": parent_slug,
        "sections": [],
    }


def _write_inventory(tmp_path: Path, pages: list[dict]) -> Path:
    inventory = {
        "source_url": "https://source.example.com",
        "crawled_at": "2026-04-12T00:00:00+00:00",
        "pages": pages,
        "assets": {"count": 0, "manifest": "assets/manifest.json"},
        "global": {},
    }
    path = tmp_path / "site-inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")
    return path


def _write_header(tmp_path: Path, nav_items: list[dict]) -> Path:
    global_dir = tmp_path / "global"
    global_dir.mkdir(exist_ok=True)
    header = {
        "type": "header",
        "template": "Site Header",
        "content": {
            "headings": [],
            "paragraphs": [],
            "images": [],
            "links": [],
            "buttons": [],
            "nav_items": nav_items,
        },
    }
    header_path = global_dir / "header.json"
    header_path.write_text(json.dumps(header), encoding="utf-8")
    return header_path


def _register_create_responses(
    rsps: responses.RequestsMock, responses_sequence: list[dict]
) -> None:
    """Register a sequence of CREATE_PAGE mock responses in order.

    Also registers the homepage GET that the client fetches once to obtain
    an anti-forgery token before making any POST.
    """
    mock_homepage(rsps)
    for payload in responses_sequence:
        rsps.add(
            responses.POST,
            CREATE_PAGE_URL,
            json=payload,
            status=200,
        )


def _create_page_bodies(rsps: responses.RequestsMock) -> list[dict]:
    """Return the JSON bodies of every POST made to CREATE_PAGE_URL, in order."""
    bodies: list[dict] = []
    for call in rsps.calls:
        if call.request.method == "POST" and CREATE_PAGE_URL in call.request.url:
            bodies.append(json.loads(call.request.body))
    return bodies


# --- _topological_sort (pure) ---


def test_topological_sort_places_parent_before_child():
    pages = [
        _inventory_page("/services/web", "services-web", parent_slug="services"),
        _inventory_page("/services", "services"),
        _inventory_page("/", "home"),
    ]

    ordered = _topological_sort(pages)
    slugs = [p["slug"] for p in ordered]

    assert slugs.index("services") < slugs.index("services-web")


def test_topological_sort_handles_three_level_nesting():
    pages = [
        _inventory_page("/a/b/c", "a-b-c", parent_slug="a-b"),
        _inventory_page("/a/b", "a-b", parent_slug="a"),
        _inventory_page("/a", "a"),
    ]

    slugs = [p["slug"] for p in _topological_sort(pages)]

    assert slugs.index("a") < slugs.index("a-b") < slugs.index("a-b-c")


def test_topological_sort_treats_missing_parent_as_top_level():
    """A page whose parent_slug isn't in the inventory still gets created."""
    pages = [
        _inventory_page("/", "home"),
        _inventory_page("/orphan", "orphan", parent_slug="missing"),
    ]

    ordered = _topological_sort(pages)
    slugs = [p["slug"] for p in ordered]

    assert "orphan" in slugs


def test_topological_sort_drops_entries_without_slug():
    pages = [
        _inventory_page("/", "home"),
        {"url": "bad"},  # no slug
    ]

    ordered = _topological_sort(pages)

    assert len(ordered) == 1
    assert ordered[0]["slug"] == "home"


def test_topological_sort_breaks_cycle_without_infinite_loop():
    """If two pages depend on each other, flush them rather than hang."""
    pages = [
        _inventory_page("/a", "a", parent_slug="b"),
        _inventory_page("/b", "b", parent_slug="a"),
    ]

    ordered = _topological_sort(pages)

    # Both pages should appear exactly once
    slugs = [p["slug"] for p in ordered]
    assert sorted(slugs) == ["a", "b"]


# --- create-pages command end-to-end ---


def test_create_pages_creates_parent_before_child(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """Parent page is created first, then children use its returned pageId."""
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/", "home"),
            _inventory_page("/services", "services"),
            _inventory_page(
                "/services/web", "services-web", parent_slug="services"
            ),
        ],
    )

    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 101, "name": "home"},
            {"pageId": 102, "name": "services"},
            {"pageId": 103, "name": "services-web"},
        ],
    )

    result = runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(inventory_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "ok"
    assert output["created"] == 3

    bodies = _create_page_bodies(mocked_responses)
    assert len(bodies) == 3
    assert bodies[0]["name"] == "home"
    assert bodies[1]["name"] == "services"
    assert "parentId" not in bodies[1]
    assert bodies[2]["name"] == "services-web"
    assert bodies[2]["parentId"] == 102


def test_create_pages_writes_page_id_map(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """The command writes a source-url → page-id map to page-id-map.json."""
    inventory_path = _write_inventory(
        tmp_path,
        [_inventory_page("/", "home"), _inventory_page("/about", "about")],
    )
    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 201, "name": "home"},
            {"pageId": 202, "name": "about"},
        ],
    )

    runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(inventory_path),
            "--json",
        ],
    )

    id_map = json.loads((tmp_path / "page-id-map.json").read_text())
    assert id_map["https://source.example.com/"] == 201
    assert id_map["https://source.example.com/about"] == 202


def test_create_pages_marks_in_menu_from_header_nav(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """Pages linked from header nav_items get includeInMenu=true, others false."""
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/", "home"),
            _inventory_page("/about", "about"),
            _inventory_page("/privacy", "privacy"),
        ],
    )
    _write_header(
        tmp_path,
        [
            {"label": "Home", "href": "https://source.example.com/", "children": []},
            {"label": "About", "href": "https://source.example.com/about", "children": []},
        ],
    )
    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 301, "name": "home"},
            {"pageId": 302, "name": "about"},
            {"pageId": 303, "name": "privacy"},
        ],
    )

    runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(inventory_path),
            "--json",
        ],
    )

    by_slug = {b["name"]: b for b in _create_page_bodies(mocked_responses)}
    assert by_slug["home"]["includeInMenu"] is True
    assert by_slug["about"]["includeInMenu"] is True
    assert by_slug["privacy"]["includeInMenu"] is False


def test_create_pages_includes_all_when_no_header_nav(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """With no header.json, every page defaults to includeInMenu=true."""
    inventory_path = _write_inventory(
        tmp_path,
        [_inventory_page("/", "home"), _inventory_page("/about", "about")],
    )
    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 401, "name": "home"},
            {"pageId": 402, "name": "about"},
        ],
    )

    runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(inventory_path),
            "--json",
        ],
    )

    bodies = _create_page_bodies(mocked_responses)
    assert all(body["includeInMenu"] is True for body in bodies)


def test_create_pages_dry_run_does_not_hit_api(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """--dry-run prints the plan without calling CREATE_PAGE."""
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/", "home"),
            _inventory_page("/services", "services"),
            _inventory_page("/services/web", "services-web", parent_slug="services"),
        ],
    )

    result = runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(inventory_path),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["dry_run"] is True
    assert len(output["plan"]) == 3
    assert [entry["slug"] for entry in output["plan"]][:2] == ["home", "services"]
    assert output["plan"][2]["parent_slug"] == "services"
    assert len(mocked_responses.calls) == 0


def test_create_pages_errors_when_inventory_missing(
    runner, mock_config, tmp_path: Path
):
    result = runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(tmp_path / "nonexistent.json"),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_create_pages_errors_when_inventory_has_no_pages(
    runner, mock_config, tmp_path: Path
):
    inventory_path = tmp_path / "site-inventory.json"
    inventory_path.write_text(json.dumps({"pages": []}), encoding="utf-8")

    result = runner.invoke(
        cli,
        [
            "migrate",
            "create-pages",
            "--inventory",
            str(inventory_path),
            "--json",
        ],
    )

    assert result.exit_code != 0
    assert "no pages" in result.output.lower()
