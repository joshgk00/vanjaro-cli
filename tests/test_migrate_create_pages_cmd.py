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


LIST_AI_PAGES_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/List"


def _register_existing_pages(
    rsps: responses.RequestsMock, existing: list[dict] | None = None
) -> None:
    """Register the AIPage/List response that ``create-pages`` uses for its
    collision pre-flight check. Defaults to an empty list (no collisions).
    """
    rsps.add(
        responses.GET,
        LIST_AI_PAGES_URL,
        json={"total": len(existing or []), "skip": 0, "take": 200, "pages": existing or []},
        status=200,
    )


def _register_create_responses(
    rsps: responses.RequestsMock,
    responses_sequence: list[dict],
    existing: list[dict] | None = None,
) -> None:
    """Register a sequence of CREATE_PAGE mock responses in order.

    Also registers the homepage GET that the client fetches once to obtain
    an anti-forgery token, and the AIPage/List response used by the slug
    collision pre-flight check.
    """
    mock_homepage(rsps)
    _register_existing_pages(rsps, existing)
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
    assert by_slug["home"]["isVisible"] is True
    assert by_slug["about"]["isVisible"] is True
    assert by_slug["privacy"]["isVisible"] is False


def test_create_pages_matches_in_menu_when_nav_uses_www_and_pages_do_not(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """Real-world case: source nav links use ``www.`` but crawl is at bare domain.

    The crawler often visits ``https://example.com/`` while the source nav
    markup links to ``https://www.example.com/page``. Without normalizing
    the host, the includeInMenu filter would treat every page as missing
    from the nav and hide them all.
    """
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/", "home"),
            _inventory_page("/about", "about"),
            _inventory_page("/hidden", "hidden"),
        ],
    )
    _write_header(
        tmp_path,
        [
            {"label": "Home", "href": "https://www.source.example.com/", "children": []},
            {"label": "About", "href": "https://www.source.example.com/about", "children": []},
        ],
    )
    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 401, "name": "home"},
            {"pageId": 402, "name": "about"},
            {"pageId": 403, "name": "hidden"},
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
    assert by_slug["home"]["isVisible"] is True
    assert by_slug["about"]["isVisible"] is True
    assert by_slug["hidden"]["isVisible"] is False


def test_create_pages_matches_in_menu_when_pages_use_www_and_nav_does_not(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """Inverse of the prior test: crawl visits the ``www.`` host but nav links
    point at the bare domain. Symmetry must hold — both sides are normalized.
    """
    inventory_path = _write_inventory(
        tmp_path,
        [
            {
                "url": "https://www.source.example.com/",
                "path": "/",
                "title": "Home",
                "slug": "home",
                "parent_slug": None,
                "sections": [],
            },
            {
                "url": "https://www.source.example.com/about",
                "path": "/about",
                "title": "About",
                "slug": "about",
                "parent_slug": None,
                "sections": [],
            },
            {
                "url": "https://www.source.example.com/hidden",
                "path": "/hidden",
                "title": "Hidden",
                "slug": "hidden",
                "parent_slug": None,
                "sections": [],
            },
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
            {"pageId": 501, "name": "home"},
            {"pageId": 502, "name": "about"},
            {"pageId": 503, "name": "hidden"},
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
    assert by_slug["home"]["isVisible"] is True
    assert by_slug["about"]["isVisible"] is True
    assert by_slug["hidden"]["isVisible"] is False


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
    assert all(body["isVisible"] is True for body in bodies)


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


# --- #2: Slug collision pre-flight ---


def test_create_pages_skips_existing_slug_and_reuses_id_for_children(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """When a page with the same name already exists, register its id for
    parenting children and skip the create POST."""
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/", "home"),
            _inventory_page("/blog", "blog"),
            _inventory_page("/blog/post-1", "blog-post-1", parent_slug="blog"),
        ],
    )

    # Existing pages: "home" already exists (id 21), "blog" does not
    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 38, "name": "blog", "path": "/blog"},
            {"pageId": 39, "name": "blog-post-1", "path": "/blog/blog-post-1"},
        ],
        existing=[{"tabId": 21, "name": "Home", "path": "/Home"}],
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
    assert output["created"] == 2
    assert output["skipped"] == 1
    assert any("home" in w.lower() and "skipping" in w.lower() for w in output["warnings"])

    # Only 2 POSTs (blog + blog-post-1), home was skipped
    bodies = _create_page_bodies(mocked_responses)
    assert len(bodies) == 2
    assert {b["name"] for b in bodies} == {"blog", "blog-post-1"}


def test_create_pages_collision_match_is_case_insensitive(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """DNN treats names case-insensitively, so "Home" and "home" must collide."""
    inventory_path = _write_inventory(
        tmp_path,
        [_inventory_page("/", "home")],
    )

    _register_create_responses(
        mocked_responses,
        [],
        existing=[{"tabId": 21, "name": "HOME", "path": "/"}],
    )

    result = runner.invoke(
        cli,
        ["migrate", "create-pages", "--inventory", str(inventory_path), "--json"],
    )

    assert result.exit_code == 0
    output = json.loads(result.output)
    assert output["created"] == 0
    assert output["skipped"] == 1


def test_create_pages_existing_parent_id_is_reused_by_children(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """A child whose parent already exists in Vanjaro should be parented
    to the existing id, not orphaned to the root."""
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/blog", "blog"),
            _inventory_page("/blog/post-1", "blog-post-1", parent_slug="blog"),
        ],
    )

    _register_create_responses(
        mocked_responses,
        [{"pageId": 99, "name": "blog-post-1", "path": "/blog/blog-post-1"}],
        existing=[{"tabId": 50, "name": "Blog", "path": "/Blog"}],
    )

    result = runner.invoke(
        cli,
        ["migrate", "create-pages", "--inventory", str(inventory_path), "--json"],
    )

    assert result.exit_code == 0
    bodies = _create_page_bodies(mocked_responses)
    assert len(bodies) == 1
    assert bodies[0]["name"] == "blog-post-1"
    assert bodies[0]["parentId"] == 50  # existing blog id, not None


# --- #3: page-url-map.json reflects actual paths ---


def test_create_pages_writes_page_url_map_with_actual_paths(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """The fresh page-url-map.json must use the path returned from the API,
    which reflects parent-aware URL nesting (e.g. /blog/<slug> not /<slug>)."""
    inventory_path = _write_inventory(
        tmp_path,
        [
            _inventory_page("/blog", "blog"),
            _inventory_page("/blog/post-1", "blog-post-1", parent_slug="blog"),
        ],
    )

    # Crawler wrote a stale page-url-map (flat slugs) — create-pages should overwrite.
    stale_map_path = tmp_path / "page-url-map.json"
    stale_map_path.write_text(json.dumps({
        "https://source.example.com/blog/post-1": "/blog-post-1",
    }), encoding="utf-8")

    _register_create_responses(
        mocked_responses,
        [
            {"pageId": 50, "name": "blog", "path": "/blog"},
            {"pageId": 51, "name": "blog-post-1", "path": "/blog/blog-post-1"},
        ],
    )

    result = runner.invoke(
        cli,
        ["migrate", "create-pages", "--inventory", str(inventory_path), "--json"],
    )

    assert result.exit_code == 0
    new_map = json.loads(stale_map_path.read_text())
    assert new_map["https://source.example.com/blog/post-1"] == "/blog/blog-post-1"
    assert new_map["https://source.example.com/blog"] == "/blog"
    # stale flat-slug entry must be gone
    assert "/blog-post-1" not in new_map.values()


def test_create_pages_skipped_existing_pages_keep_their_path_in_url_map(
    runner, mock_config, tmp_path: Path, mocked_responses
):
    """When a page is skipped due to collision, its existing path should
    still appear in the page-url-map so rewrite-urls can target it."""
    inventory_path = _write_inventory(
        tmp_path,
        [_inventory_page("/about", "about")],
    )

    _register_create_responses(
        mocked_responses,
        [],
        existing=[{"tabId": 99, "name": "About", "path": "/About"}],
    )

    result = runner.invoke(
        cli,
        ["migrate", "create-pages", "--inventory", str(inventory_path), "--json"],
    )

    assert result.exit_code == 0
    url_map_path = tmp_path / "page-url-map.json"
    assert url_map_path.exists()
    url_map = json.loads(url_map_path.read_text())
    assert url_map["https://source.example.com/about"] == "/About"
