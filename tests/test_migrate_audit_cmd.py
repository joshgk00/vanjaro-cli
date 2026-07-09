"""Tests for vanjaro migrate audit-structure command."""

from __future__ import annotations

import json

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, FAKE_COOKIES, mock_homepage

GET_PAGES_URL = f"{BASE_URL}/API/PersonaBar/Pages/GetPageList"

HOME_PATH = "/"
ABOUT_PATH = "/about"
HOME_URL = BASE_URL
ABOUT_URL = f"{BASE_URL}/about"

# ---------------------------------------------------------------------------
# HTML fixture builders
# ---------------------------------------------------------------------------


def _make_clean_page_html(guid: str = "aaaa-1111") -> str:
    return (
        "<html><body>"
        "<div id='dnn_ContentPane'><div class='vj-wrapper'><div id='vjEditor'>"
        f"<div data-guid='{guid}' published='true'><h1 class='vj-heading head-style-1'>Title</h1></div>"
        "<section>"
        "<h2 class='vj-heading head-style-2'>About</h2>"
        "<p class='vj-text paragraph-style-1'>Content here.</p>"
        "<picture>"
        "<source srcset='/DesktopModules/Vanjaro/API/Page/.versions/img.webp' type='image/webp'>"
        "<img src='/images/img.jpg' alt='img'>"
        "</picture>"
        "</section>"
        "<section><p class='vj-text paragraph-style-2'>More content.</p></section>"
        "<section><p>Footer.</p></section>"
        "</div></div></div>"
        "</body></html>"
    )


def _make_dirty_page_html() -> str:
    return (
        "<html><body>"
        "<div id='dnn_ContentPane'><div class='vj-wrapper'><div id='vjEditor'>"
        "<div style='color: red;'>"
        "<h1 style='font-size: 36px;'>No theme classes</h1>"
        "<img src='/images/hero.jpg'>"
        "</div>"
        "</div></div></div>"
        "</body></html>"
    )


def _make_pages_response(pages: list[dict]) -> dict:
    return {"pages": pages}


def _make_page_item(
    tab_id: int,
    name: str,
    url: str,
    child_count: int = 0,
    isspecial: bool = False,
    tabpath: str | None = None,
) -> dict:
    return {
        "id": tab_id,
        "name": name,
        "url": url,
        "parentId": -1,
        "level": 0,
        "status": "Visible",
        "publishStatus": "Published",
        "childCount": child_count,
        "tabpath": tabpath if tabpath is not None else url,
        "isspecial": isspecial,
        "pageType": "normal",
    }


# ---------------------------------------------------------------------------
# Command: error cases
# ---------------------------------------------------------------------------


def test_audit_structure_no_options_errors(runner, mock_config):
    result = runner.invoke(cli, ["migrate", "audit-structure"])
    assert result.exit_code != 0
    assert "Provide at least one --page" in result.output or "Provide at least one --page" in (result.output + str(result.exception))


@responses.activate
def test_audit_structure_page_fetch_failure_errors(runner, mock_config):
    mock_homepage(None)
    responses.add(responses.GET, ABOUT_URL, status=500)
    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/about"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Command: single page, human output
# ---------------------------------------------------------------------------


@responses.activate
def test_audit_structure_single_page_human_output(runner, mock_config):
    mock_homepage(None)
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/"])

    assert result.exit_code == 0
    assert "Site composite score" in result.output
    assert "inline-styles" in result.output


@responses.activate
def test_audit_structure_single_page_dirty_html(runner, mock_config):
    mock_homepage(None)
    responses.add(responses.GET, HOME_URL, body=_make_dirty_page_html(), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/"])

    assert result.exit_code == 0
    assert "Site composite score" in result.output


# ---------------------------------------------------------------------------
# Command: --as-json output
# ---------------------------------------------------------------------------


@responses.activate
def test_audit_structure_json_output_schema(runner, mock_config):
    mock_homepage(None)
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "pages" in data
    assert "site_checks" in data
    assert "score" in data
    assert len(data["pages"]) == 1
    page = data["pages"][0]
    assert "checks" in page
    assert "inline-styles" in page["checks"]
    assert "theme-classes" in page["checks"]
    assert "responsive-images" in page["checks"]
    assert "composition" in page["checks"]
    assert "global-blocks" in data["site_checks"]
    for check_name, finding in page["checks"].items():
        assert "score" in finding
        assert "summary" in finding
        assert "details" in finding
        assert 0 <= finding["score"] <= 100


@responses.activate
def test_audit_structure_json_has_check_details(runner, mock_config):
    mock_homepage(None)
    responses.add(responses.GET, ABOUT_URL, body=_make_dirty_page_html(), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/about", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    page = data["pages"][0]
    # Dirty page should have low inline-styles score and details
    inline = page["checks"]["inline-styles"]
    assert inline["score"] < 100
    assert len(inline["details"]) > 0


# ---------------------------------------------------------------------------
# Command: --json (write to file)
# ---------------------------------------------------------------------------


@responses.activate
def test_audit_structure_writes_json_file(runner, mock_config, tmp_path):
    mock_homepage(None)
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)

    output_path = tmp_path / "audit.json"
    result = runner.invoke(
        cli,
        ["migrate", "audit-structure", "--page", "/", "--json", str(output_path)],
    )

    assert result.exit_code == 0
    assert output_path.exists()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "pages" in data
    assert "site_checks" in data
    assert "score" in data
    assert f"written to {output_path}" in result.output


# ---------------------------------------------------------------------------
# Command: --all (discover pages via API)
# ---------------------------------------------------------------------------


@responses.activate
def test_audit_structure_all_discovers_pages(runner, mock_config):
    mock_homepage(None)
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=_make_pages_response([
            _make_page_item(1, "Home", "/"),
            _make_page_item(2, "About", "/about"),
        ]),
        status=200,
    )
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)
    responses.add(responses.GET, ABOUT_URL, body=_make_clean_page_html("bbbb-2222"), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["pages"]) == 2


@responses.activate
def test_audit_structure_all_partial_fetch_failure_continues(runner, mock_config):
    """If one page 404s, the others still get audited."""
    mock_homepage(None)
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=_make_pages_response([
            _make_page_item(1, "Home", "/"),
            _make_page_item(2, "Missing", "/missing"),
        ]),
        status=200,
    )
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)
    responses.add(responses.GET, f"{BASE_URL}/missing", status=404)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["pages"]) == 1
    assert "fetch_errors" in data
    assert len(data["fetch_errors"]) == 1


@responses.activate
def test_audit_structure_all_no_pages_found_errors(runner, mock_config):
    mock_homepage(None)
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=_make_pages_response([]),
        status=200,
    )

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Command: multiple --page args
# ---------------------------------------------------------------------------


@responses.activate
def test_audit_structure_multiple_pages(runner, mock_config):
    mock_homepage(None)
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)
    responses.add(responses.GET, ABOUT_URL, body=_make_clean_page_html("cccc-3333"), status=200)

    result = runner.invoke(
        cli,
        ["migrate", "audit-structure", "--page", "/", "--page", "/about", "--as-json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["pages"]) == 2


# ---------------------------------------------------------------------------
# JSON schema contract (gap-report consumer spec)
# ---------------------------------------------------------------------------


@responses.activate
def test_json_report_schema_contract(runner, mock_config):
    """The JSON output must conform to the schema the gap-report feature expects."""
    mock_homepage(None)
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/", "--as-json"])
    data = json.loads(result.output)

    # Top-level keys
    assert set(data.keys()) >= {"pages", "site_checks", "score"}
    assert isinstance(data["score"], (int, float))
    assert 0 <= data["score"] <= 100

    # Per-page schema
    page = data["pages"][0]
    assert set(page.keys()) >= {"url", "checks", "score"}
    assert isinstance(page["score"], (int, float))

    for check_name in ("inline-styles", "theme-classes", "responsive-images", "composition"):
        check = page["checks"][check_name]
        assert isinstance(check["score"], int)
        assert isinstance(check["summary"], str)
        assert isinstance(check["details"], list)

    # Site checks
    gb = data["site_checks"]["global-blocks"]
    assert isinstance(gb["score"], int)
    assert isinstance(gb["summary"], str)
    assert isinstance(gb["details"], list)


# ---------------------------------------------------------------------------
# System-page filtering (Task A)
# ---------------------------------------------------------------------------


@responses.activate
def test_audit_structure_all_excludes_system_pages_by_default(runner, mock_config):
    """DNN system pages (isspecial=true, known DNN tabpaths) are filtered from --all."""
    mock_homepage(None)
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=_make_pages_response([
            _make_page_item(1, "Home", "/", isspecial=True, tabpath="/Home"),
            _make_page_item(2, "About", "/about"),
            _make_page_item(3, "Signin", f"{BASE_URL}/Signin", isspecial=True, tabpath="/Signin"),
            _make_page_item(4, "Search Results", f"{BASE_URL}/Search-Results", isspecial=False, tabpath="/SearchResults"),
            _make_page_item(5, "404 Error Page", f"{BASE_URL}/404-Error-Page", isspecial=False, tabpath="/404ErrorPage"),
        ]),
        status=200,
    )
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)
    responses.add(responses.GET, f"{BASE_URL}/about", body=_make_clean_page_html("bbbb-2222"), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    audited_urls = [p["url"] for p in data["pages"]]
    assert len(audited_urls) == 2
    assert not any("Signin" in u or "Search-Results" in u or "404" in u for u in audited_urls)


@responses.activate
def test_audit_structure_all_include_system_flag_keeps_system_pages(runner, mock_config):
    """--include-system overrides the default filter and includes DNN system pages."""
    mock_homepage(None)
    responses.add(
        responses.GET,
        GET_PAGES_URL,
        json=_make_pages_response([
            _make_page_item(1, "Home", "/", isspecial=True, tabpath="/Home"),
            _make_page_item(2, "Signin", f"{BASE_URL}/Signin", isspecial=True, tabpath="/Signin"),
        ]),
        status=200,
    )
    responses.add(responses.GET, HOME_URL, body=_make_clean_page_html(), status=200)
    responses.add(responses.GET, f"{BASE_URL}/Signin", body=_make_clean_page_html("sig-1"), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all", "--include-system", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["pages"]) == 2


@responses.activate
def test_audit_structure_page_flag_never_filtered(runner, mock_config):
    """Explicit --page paths are never filtered, even if they are system pages."""
    mock_homepage(None)
    responses.add(responses.GET, f"{BASE_URL}/Signin", body=_make_clean_page_html("sig-1"), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--page", "/Signin", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data["pages"]) == 1


# ---------------------------------------------------------------------------
# Child-portal alias handling
# ---------------------------------------------------------------------------


def _write_child_portal_config(config_file, base_url: str) -> None:
    config_file.write_text(json.dumps({
        "active_profile": "default",
        "profiles": {"default": {"base_url": base_url, "portal_id": 2, "cookies": FAKE_COOKIES}},
    }))


@responses.activate
def test_audit_structure_all_child_portal_alias_not_doubled(runner, mock_config):
    """Page URLs on a child portal already carry the alias — the audit must not
    join them onto the aliased base URL a second time."""
    child_base = f"{BASE_URL}/child"
    _write_child_portal_config(mock_config, child_base)
    responses.add(
        responses.GET,
        f"{child_base}/API/PersonaBar/Pages/GetPageList",
        json=_make_pages_response([
            _make_page_item(1, "Home", f"{child_base}/", isspecial=True, tabpath="/Home"),
            _make_page_item(2, "About", f"{child_base}/about", tabpath="/About"),
        ]),
        status=200,
    )
    responses.add(responses.GET, f"{child_base}/", body=_make_clean_page_html(), status=200)
    responses.add(responses.GET, f"{child_base}/about", body=_make_clean_page_html("bbbb-2222"), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    audited_urls = sorted(p["url"] for p in data["pages"])
    assert audited_urls == [f"{child_base}/", f"{child_base}/about"]


@responses.activate
def test_audit_structure_all_child_portal_home_not_filtered_as_system(runner, mock_config):
    """The child-portal home page has an alias-prefixed path (not a bare ``/``)
    but is still a content page — the isspecial filter must leave it through."""
    child_base = f"{BASE_URL}/child"
    _write_child_portal_config(mock_config, child_base)
    responses.add(
        responses.GET,
        f"{child_base}/API/PersonaBar/Pages/GetPageList",
        json=_make_pages_response([
            _make_page_item(1, "Home", f"{child_base}/", isspecial=True, tabpath="/Home"),
            _make_page_item(2, "Signin", f"{child_base}/Signin", isspecial=True, tabpath="/Signin"),
        ]),
        status=200,
    )
    responses.add(responses.GET, f"{child_base}/", body=_make_clean_page_html(), status=200)

    result = runner.invoke(cli, ["migrate", "audit-structure", "--all", "--as-json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    audited_urls = [p["url"] for p in data["pages"]]
    assert audited_urls == [f"{child_base}/"]
