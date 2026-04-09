"""Tests for vanjaro migrate verify / verify-all."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_CONTENT_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Get"
GET_PAGE_DETAILS_URL = f"{BASE_URL}/API/PersonaBar/Pages/GetPageDetails"
LIST_GLOBAL_BLOCKS_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/List"
GET_GLOBAL_BLOCK_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Get"

SOURCE_URL = "https://example.com"
HOME_URL = f"{SOURCE_URL}/"
ABOUT_URL = f"{SOURCE_URL}/about"


# -- Test helpers --


def _write_json(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_source_section(
    *,
    headings: list[str] | None = None,
    paragraphs: list[str] | None = None,
    images: list[dict] | None = None,
    buttons: list[dict] | None = None,
    section_type: str = "content",
) -> dict:
    return {
        "type": section_type,
        "template": "Rich Text Block",
        "content": {
            "headings": headings or [],
            "paragraphs": paragraphs or [],
            "images": images or [],
            "links": [],
            "buttons": buttons or [],
        },
    }


def _make_migrated_tree(
    headings: list[str],
    paragraphs: list[str],
    *,
    images: list[str] | None = None,
    links: list[str] | None = None,
) -> list[dict]:
    children: list[dict] = []
    for index, heading in enumerate(headings):
        children.append(
            {
                "type": "heading",
                "tagName": "h2",
                "content": heading,
                "attributes": {"id": f"h-{index}"},
            }
        )
    for index, paragraph in enumerate(paragraphs):
        children.append(
            {
                "type": "text",
                "content": paragraph,
                "attributes": {"id": f"p-{index}"},
            }
        )
    for index, src in enumerate(images or []):
        children.append(
            {
                "type": "image",
                "attributes": {"id": f"i-{index}", "src": src},
            }
        )
    for index, href in enumerate(links or []):
        children.append(
            {
                "type": "link",
                "tagName": "a",
                "content": f"Link {index}",
                "attributes": {"id": f"l-{index}", "href": href},
            }
        )
    return [
        {
            "type": "section",
            "attributes": {"id": "s-1"},
            "components": children,
        }
    ]


def _make_manifest_entry(source_url: str, vanjaro_url: str | None) -> dict:
    return {
        "source_url": source_url,
        "local_file": source_url.rsplit("/", 1)[-1] or "file",
        "vanjaro_url": vanjaro_url,
        "uploaded": vanjaro_url is not None,
    }


def _content_get_payload(components: list[dict]) -> dict:
    return {
        "pageId": 0,
        "contentJSON": json.dumps(components),
        "styleJSON": "[]",
        "version": 1,
        "isPublished": True,
        "locale": "en-US",
    }


def _page_details_payload(title: str, description: str = "") -> dict:
    return {
        "page": {
            "tabId": 1,
            "name": title,
            "title": title,
            "description": description,
            "url": "/home",
            "keywords": "",
            "status": "published",
        }
    }


def _build_inventory_tree(
    tmp_path: Path,
    *,
    pages: list[tuple[str, str, dict]],
    manifest: list[dict],
    include_url_map: dict[str, str] | None = None,
) -> Path:
    """Build a full inventory tree at ``tmp_path`` and return the inventory path."""
    root = tmp_path / "migration"
    root.mkdir(parents=True, exist_ok=True)

    pages_summary: list[dict] = []
    for source_url, slug, section in pages:
        section_path = root / "pages" / slug / "section-001-content.json"
        _write_json(section_path, section)
        pages_summary.append({
            "url": source_url,
            "path": "/" + slug if slug != "home" else "/",
            "title": section["content"]["headings"][0] if section["content"].get("headings") else "",
            "slug": slug,
            "sections": [
                {
                    "file": f"pages/{slug}/section-001-content.json",
                    "type": section["type"],
                    "template": section["template"],
                }
            ],
        })

    _write_json(root / "assets" / "manifest.json", manifest)

    inventory = {
        "source_url": SOURCE_URL,
        "crawled_at": "2026-04-09T00:00:00+00:00",
        "pages": pages_summary,
        "assets": {"count": len(manifest), "manifest": "assets/manifest.json"},
        "global": {},
    }
    inventory_path = root / "site-inventory.json"
    _write_json(inventory_path, inventory)

    if include_url_map is not None:
        _write_json(root / "page-url-map.json", include_url_map)

    return inventory_path


def _register_content_and_details(
    rsps: responses.RequestsMock,
    page_id: int,
    components: list[dict],
    *,
    title: str = "Welcome",
    description: str = "",
) -> None:
    rsps.add(
        responses.GET,
        GET_CONTENT_URL,
        json=_content_get_payload(components),
        status=200,
    )
    rsps.add(
        responses.GET,
        GET_PAGE_DETAILS_URL,
        json=_page_details_payload(title, description),
        status=200,
    )


# -- verify (single page) --


@responses.activate
def test_verify_happy_path(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(
        headings=["Welcome"],
        paragraphs=["Intro copy."],
        images=[{"src": "https://example.com/hero.jpg", "alt": ""}],
    )
    manifest = [
        _make_manifest_entry("https://example.com/hero.jpg", "/Portals/0/hero.jpg"),
    ]
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=manifest,
    )

    migrated = _make_migrated_tree(
        ["Welcome"], ["Intro copy."], images=["/Portals/0/hero.jpg"]
    )
    _register_content_and_details(responses, 10, migrated, title="Welcome")

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passed"
    assert payload["source_url"] == HOME_URL
    assert payload["page_id"] == 10
    assert payload["text"]["passed"] is True
    assert payload["images"]["hard_gaps"] == []


@responses.activate
def test_verify_text_gap_exits_nonzero(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(
        headings=["Welcome", "Our Team", "Services"],
        paragraphs=["Founded in 1998.", "We build reliable tools.", "Contact us today."],
    )
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )

    migrated = _make_migrated_tree(["Welcome"], ["Founded in 1998."])
    _register_content_and_details(responses, 10, migrated)

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    assert payload["text"]["passed"] is False
    assert "Our Team" in payload["text"]["missing_headings"]


@responses.activate
def test_verify_hard_image_gap_exits_nonzero(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(
        headings=["Hi"],
        paragraphs=["Text."],
        images=[{"src": "https://example.com/missing.jpg", "alt": ""}],
    )
    manifest = [_make_manifest_entry("https://example.com/missing.jpg", None)]
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=manifest,
    )

    migrated = _make_migrated_tree(["Hi"], ["Text."])
    _register_content_and_details(responses, 10, migrated, title="Hi")

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    gap_types = {gap["type"] for gap in payload["images"]["hard_gaps"]}
    assert "not_uploaded" in gap_types


@responses.activate
def test_verify_writes_output_file(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(headings=["Hi"], paragraphs=["t"])
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )
    migrated = _make_migrated_tree(["Hi"], ["t"])
    _register_content_and_details(responses, 10, migrated, title="Hi")

    output_file = tmp_path / "report.json"

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--output", str(output_file),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output_file.exists()
    written = json.loads(output_file.read_text())
    assert written["status"] == "passed"


@responses.activate
def test_verify_missing_inventory_file_errors_cleanly(runner, mock_config, tmp_path):
    mock_homepage()

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(tmp_path / "missing.json"),
            "--source-url", HOME_URL,
            "--page-id", "10",
        ],
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


@responses.activate
def test_verify_content_404_hard_fails(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(headings=["Hi"], paragraphs=["t"])
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )
    responses.add(
        responses.GET,
        GET_CONTENT_URL,
        json={"Message": "Not found"},
        status=404,
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "999",
        ],
    )

    assert result.exit_code != 0
    assert "999" in result.output or "content" in result.output.lower()


@responses.activate
def test_verify_header_block_missing_errors(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(headings=["Hi"], paragraphs=["t"])
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )
    _write_json(
        inventory_path.parent / "global" / "header.json",
        {"type": "header", "template": "Site Header", "content": {"headings": [], "links": []}},
    )

    migrated = _make_migrated_tree(["Hi"], ["t"])
    _register_content_and_details(responses, 10, migrated, title="Hi")
    responses.add(
        responses.GET,
        LIST_GLOBAL_BLOCKS_URL,
        json={"total": 0, "blocks": []},
        status=200,
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--header-block-name", "Site Header",
        ],
    )

    assert result.exit_code != 0
    assert "Site Header" in result.output


@responses.activate
def test_verify_threshold_override_accepted(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(
        headings=["Welcome", "Our Team"],
        paragraphs=["Intro.", "Details."],
    )
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )
    # Only half the content makes it across — would fail at the default 0.9
    # threshold, but passes at 0.5.
    migrated = _make_migrated_tree(["Welcome"], ["Intro."])
    _register_content_and_details(responses, 10, migrated, title="Welcome")

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--threshold", "0.5",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["text"]["threshold"] == 0.5
    assert payload["text"]["passed"] is True


# -- verify-all (batch) --


@responses.activate
def test_verify_all_mixed_results(runner, mock_config, tmp_path):
    mock_homepage()
    home_section = _make_source_section(headings=["Welcome"], paragraphs=["Copy."])
    about_section = _make_source_section(
        headings=["About", "Team", "Services"],
        paragraphs=["p1", "p2", "p3"],
    )

    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[
            (HOME_URL, "home", home_section),
            (ABOUT_URL, "about", about_section),
        ],
        manifest=[],
    )
    page_id_map_file = _write_json(
        tmp_path / "page-id-map.json",
        {HOME_URL: 10, ABOUT_URL: 11},
    )

    home_migrated = _make_migrated_tree(["Welcome"], ["Copy."])
    about_migrated = _make_migrated_tree(["About"], ["p1"])  # misses most text

    # Responses are consumed in registration order by URL, so register
    # pairs for each page.
    responses.add(
        responses.GET,
        GET_CONTENT_URL,
        json=_content_get_payload(home_migrated),
        status=200,
    )
    responses.add(
        responses.GET,
        GET_PAGE_DETAILS_URL,
        json=_page_details_payload("Welcome"),
        status=200,
    )
    responses.add(
        responses.GET,
        GET_CONTENT_URL,
        json=_content_get_payload(about_migrated),
        status=200,
    )
    responses.add(
        responses.GET,
        GET_PAGE_DETAILS_URL,
        json=_page_details_payload("About"),
        status=200,
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "verify-all",
            "--inventory", str(inventory_path),
            "--page-id-map", str(page_id_map_file),
            "--json",
        ],
    )

    assert result.exit_code == 1  # one failure → batch exit code is 1
    payload = json.loads(result.output)
    assert payload["pages"] == {"passed": 1, "failed": 1, "skipped": 0}
    assert len(payload["reports"]) == 2
    statuses = {report["source_url"]: report["status"] for report in payload["reports"]}
    assert statuses[HOME_URL] == "passed"
    assert statuses[ABOUT_URL] == "failed"


@responses.activate
def test_verify_all_header_block_fetched_once_for_batch(runner, mock_config, tmp_path):
    mock_homepage()
    home_section = _make_source_section(headings=["Welcome"], paragraphs=["Copy."])
    about_section = _make_source_section(headings=["About"], paragraphs=["About copy."])
    contact_section = _make_source_section(headings=["Contact"], paragraphs=["Email us."])

    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[
            (HOME_URL, "home", home_section),
            (ABOUT_URL, "about", about_section),
            (f"{SOURCE_URL}/contact", "contact", contact_section),
        ],
        manifest=[],
    )
    _write_json(
        inventory_path.parent / "global" / "header.json",
        {
            "type": "header",
            "template": "Site Header",
            "content": {
                "headings": [],
                "paragraphs": [],
                "images": [],
                "links": [{"text": "Home", "href": "/"}],
                "buttons": [],
            },
        },
    )
    page_id_map_file = _write_json(
        tmp_path / "page-id-map.json",
        {HOME_URL: 10, ABOUT_URL: 11, f"{SOURCE_URL}/contact": 12},
    )

    header_block = {
        "id": 1,
        "guid": "hdr-guid",
        "name": "Site Header",
        "category": "site",
        "version": 1,
        "isPublished": True,
        "contentJSON": json.dumps([
            {
                "type": "section",
                "attributes": {"id": "hdr"},
                "components": [
                    {
                        "type": "link",
                        "tagName": "a",
                        "content": "Home",
                        "attributes": {"id": "nav-home", "href": "/"},
                    }
                ],
            }
        ]),
        "styleJSON": "[]",
    }

    responses.add(
        responses.GET,
        LIST_GLOBAL_BLOCKS_URL,
        json={"total": 1, "blocks": [header_block]},
        status=200,
    )
    responses.add(
        responses.GET,
        GET_GLOBAL_BLOCK_URL,
        json=header_block,
        status=200,
    )

    for page_id, title in ((10, "Welcome"), (11, "About"), (12, "Contact")):
        migrated = _make_migrated_tree(
            [title],
            [home_section["content"]["paragraphs"][0]] if page_id == 10 else ["x"],
        )
        responses.add(
            responses.GET,
            GET_CONTENT_URL,
            json=_content_get_payload(migrated),
            status=200,
        )
        responses.add(
            responses.GET,
            GET_PAGE_DETAILS_URL,
            json=_page_details_payload(title),
            status=200,
        )

    result = runner.invoke(
        cli,
        [
            "migrate", "verify-all",
            "--inventory", str(inventory_path),
            "--page-id-map", str(page_id_map_file),
            "--header-block-name", "Site Header",
            "--threshold", "0.3",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output

    list_calls = [c for c in responses.calls if "AIGlobalBlock/List" in c.request.url]
    get_block_calls = [c for c in responses.calls if "AIGlobalBlock/Get" in c.request.url]
    assert len(list_calls) == 1, f"expected 1 list call, got {len(list_calls)}"
    assert len(get_block_calls) == 1, f"expected 1 get call, got {len(get_block_calls)}"

    payload = json.loads(result.output)
    assert len(payload["reports"]) == 3
    for report in payload["reports"]:
        assert report["header"]["status"] == "match"


@responses.activate
def test_verify_rejects_non_integer_page_id_map_value(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(headings=["Hi"], paragraphs=["t"])
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )
    bad_map_file = _write_json(
        tmp_path / "page-id-map.json",
        {HOME_URL: "not-a-number"},
    )

    result = runner.invoke(
        cli,
        [
            "migrate", "verify-all",
            "--inventory", str(inventory_path),
            "--page-id-map", str(bad_map_file),
        ],
    )

    assert result.exit_code != 0
    assert "non-integer" in result.output.lower() or "integer" in result.output.lower()


@responses.activate
def test_verify_missing_global_source_file_errors(runner, mock_config, tmp_path):
    mock_homepage()
    section = _make_source_section(headings=["Hi"], paragraphs=["t"])
    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[(HOME_URL, "home", section)],
        manifest=[],
    )
    # Note: no global/header.json written alongside the inventory.

    migrated = _make_migrated_tree(["Hi"], ["t"])
    _register_content_and_details(responses, 10, migrated, title="Hi")

    result = runner.invoke(
        cli,
        [
            "migrate", "verify",
            "--inventory", str(inventory_path),
            "--source-url", HOME_URL,
            "--page-id", "10",
            "--header-block-name", "Site Header",
        ],
    )

    assert result.exit_code != 0
    assert "header.json" in result.output.lower() or "not found" in result.output.lower()


@responses.activate
def test_verify_all_skips_pages_missing_from_id_map(runner, mock_config, tmp_path):
    mock_homepage()
    home_section = _make_source_section(headings=["Welcome"], paragraphs=["Copy."])
    about_section = _make_source_section(headings=["About"], paragraphs=["About copy."])

    inventory_path = _build_inventory_tree(
        tmp_path,
        pages=[
            (HOME_URL, "home", home_section),
            (ABOUT_URL, "about", about_section),
        ],
        manifest=[],
    )
    page_id_map_file = _write_json(
        tmp_path / "page-id-map.json",
        {HOME_URL: 10},  # about is missing — should be skipped
    )

    home_migrated = _make_migrated_tree(["Welcome"], ["Copy."])
    _register_content_and_details(responses, 10, home_migrated, title="Welcome")

    result = runner.invoke(
        cli,
        [
            "migrate", "verify-all",
            "--inventory", str(inventory_path),
            "--page-id-map", str(page_id_map_file),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["pages"] == {"passed": 1, "failed": 0, "skipped": 1}
    skipped = [r for r in payload["reports"] if r["status"] == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["source_url"] == ABOUT_URL
