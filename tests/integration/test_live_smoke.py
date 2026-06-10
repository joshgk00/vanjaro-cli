"""Live smoke tests: exercise every major CLI surface against a real site.

Read-only tests verify the API contracts the unit-test mocks assume.
Lifecycle tests create uniquely-named resources and always clean them up,
even on assertion failure.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from tests.integration.conftest import LiveCli, unique_name

pytestmark = pytest.mark.integration

# 1x1 transparent PNG — smallest valid upload payload
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

SMOKE_CONTENT = {
    "components": [
        {
            "type": "text",
            "tagName": "div",
            "content": "Integration smoke content",
            "attributes": {"id": "it-smoke-text"},
        }
    ],
    "styles": [],
}

SMOKE_BLOCK = {
    "contentJSON": [
        {
            "type": "text",
            "tagName": "section",
            "content": "Integration smoke block",
        }
    ],
    "styleJSON": [],
}


def find_first_key(data: object, *candidates: str) -> object | None:
    """Recursively find the first matching key (case-insensitive) in a payload."""
    lowered = {c.lower() for c in candidates}
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in lowered and value not in (None, "", 0):
                return value
        for value in data.values():
            found = find_first_key(value, *candidates)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_first_key(item, *candidates)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# Read-only contract checks
# ---------------------------------------------------------------------------


def test_health_reports_versions(live_cli: LiveCli) -> None:
    health = live_cli.run_json("site", "health")
    assert health["status"].lower() == "ok"
    assert health["dnn_version"]
    assert health["vanjaro_version"]


def test_auth_status_session_valid(live_cli: LiveCli) -> None:
    result = live_cli.run_ok("auth", "status", "--json")
    payload = json.loads(result.output)
    assert find_first_key(payload, "authenticated", "status", "logged_in") is not None


def test_pages_list_returns_pages(live_cli: LiveCli) -> None:
    pages = live_cli.run_json("pages", "list")
    assert isinstance(pages, list) and pages
    assert find_first_key(pages[0], "id", "page_id", "tab_id") is not None


def test_site_info_summary(live_cli: LiveCli) -> None:
    info = live_cli.run_json("site", "info")
    assert isinstance(info, dict) and info


def test_site_nav_tree(live_cli: LiveCli) -> None:
    live_cli.run_ok("site", "nav", "--json")


def test_templates_list_nonempty(live_cli: LiveCli) -> None:
    templates = live_cli.run_json("templates", "list")
    assert isinstance(templates, list) and templates


def test_branding_get(live_cli: LiveCli) -> None:
    branding = live_cli.run_json("branding", "get")
    assert find_first_key(branding, "siteName", "site_name", "name") is not None


def test_theme_get_controls(live_cli: LiveCli) -> None:
    theme = live_cli.run_json("theme", "get")
    assert theme  # controls list or category map — must not be empty


def test_assets_folders_root_exists(live_cli: LiveCli) -> None:
    folders = live_cli.run_json("assets", "folders")
    assert isinstance(folders, list) and folders


def test_custom_blocks_list(live_cli: LiveCli) -> None:
    result = live_cli.run_json("custom-blocks", "list")
    assert isinstance(result, list)


def test_global_blocks_list(live_cli: LiveCli) -> None:
    result = live_cli.run_json("global-blocks", "list")
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Lifecycle tests (create → use → always delete)
# ---------------------------------------------------------------------------


def test_page_content_lifecycle(live_cli: LiveCli, tmp_path: Path) -> None:
    """Create a hidden page, push content, publish it, then delete it."""
    title = unique_name("it-smoke-page")
    created = live_cli.run_json("pages", "create", "--title", title, "--hidden")
    page_id = created["page_id"]
    assert page_id

    try:
        fetched = live_cli.run_json("pages", "get", str(page_id))
        assert find_first_key(fetched, "id", "page_id", "tab_id")

        content_file = tmp_path / "content.json"
        content_file.write_text(json.dumps(SMOKE_CONTENT))
        live_cli.run_ok("content", "update", str(page_id), "--file", str(content_file), "--json")

        content = live_cli.run_json("content", "get", str(page_id))
        assert "Integration smoke content" in json.dumps(content)

        live_cli.run_ok("content", "publish", str(page_id), "--json")
    finally:
        live_cli.run_ok("pages", "delete", str(page_id), "--force", "--json")


def test_page_seo_roundtrip(live_cli: LiveCli) -> None:
    """SEO description set via seo-update must read back via seo."""
    title = unique_name("it-smoke-seo")
    description = f"Smoke description {title}"
    created = live_cli.run_json("pages", "create", "--title", title, "--hidden")
    page_id = created["page_id"]

    try:
        live_cli.run_ok(
            "pages", "seo-update", str(page_id), "--description", description, "--json"
        )
        seo = live_cli.run_json("pages", "seo", str(page_id))
        assert description in json.dumps(seo)
    finally:
        live_cli.run_ok("pages", "delete", str(page_id), "--force", "--json")


def test_custom_block_lifecycle(live_cli: LiveCli, tmp_path: Path) -> None:
    """Register a custom block, confirm it lists, then delete it."""
    name = unique_name("it-smoke-custom")
    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps(SMOKE_BLOCK))

    created = live_cli.run_json(
        "custom-blocks", "create", "--name", name, "--category", "general",
        "--file", str(block_file),
    )
    guid = created["guid"]
    assert guid

    try:
        blocks = live_cli.run_json("custom-blocks", "list")
        assert any(name in json.dumps(block) for block in blocks)
    finally:
        live_cli.run_ok("custom-blocks", "delete", guid, "--force", "--json")


def test_global_block_lifecycle(live_cli: LiveCli, tmp_path: Path) -> None:
    """Create, fetch, publish, and delete a global block."""
    name = unique_name("it-smoke-global")
    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps(SMOKE_BLOCK))

    created = live_cli.run_json(
        "global-blocks", "create", "--name", name, "--category", "general",
        "--file", str(block_file),
    )
    guid = created["guid"]
    assert guid

    try:
        fetched = live_cli.run_json("global-blocks", "get", guid)
        assert name in json.dumps(fetched)
        live_cli.run_ok("global-blocks", "publish", guid, "--json")
    finally:
        live_cli.run_ok("global-blocks", "delete", guid, "--force", "--json")


def test_asset_upload_delete(live_cli: LiveCli, tmp_path: Path) -> None:
    """Upload a tiny PNG and delete it again."""
    file_name = f"{unique_name('it-smoke-asset')}.png"
    png_file = tmp_path / file_name
    png_file.write_bytes(TINY_PNG)

    uploaded = live_cli.run_json("assets", "upload", str(png_file), "--folder", "Images/")
    file_id = find_first_key(uploaded, "fileId", "file_id", "id")
    assert file_id, f"Upload response had no file id — actual shape: {uploaded}"

    live_cli.run_ok("assets", "delete", str(file_id), "--force", "--json")
