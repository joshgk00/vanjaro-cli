"""Tests for vanjaro content commands (VanjaroAI endpoints)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

GET_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Get"
UPDATE_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Update"
PUBLISH_PAGE_URL = f"{BASE_URL}/API/VanjaroAI/AIPage/Publish"

SAMPLE_COMPONENTS = [{"type": "text", "content": "Hello world", "attributes": {}}]
SAMPLE_STYLES = [{"selectors": [".hero"], "style": {"color": "red"}}]

SAMPLE_API_RESPONSE = {
    "pageId": 10,
    "tabId": 10,
    "contentJSON": json.dumps(SAMPLE_COMPONENTS),
    "styleJSON": json.dumps(SAMPLE_STYLES),
    "content": "<p>Hello world</p>",
    "style": ".hero { color: red; }",
    "version": 3,
    "isPublished": True,
    "locale": "en-US",
}


@responses.activate
def test_content_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    result = runner.invoke(cli, ["content", "get", "10"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["page_id"] == 10
    assert data["locale"] == "en-US"
    assert data["version"] == 3
    assert data["is_published"] is True
    assert len(data["components"]) == 1
    assert data["components"][0]["type"] == "text"


@responses.activate
def test_content_get_sends_correct_params(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    api_call = [c for c in responses.calls if "AIPage/Get" in c.request.url][0]
    assert api_call.request.params["pageId"] == "10"
    assert api_call.request.params["locale"] == "fr-FR"
    assert api_call.request.params["includeDraft"] == "true"


@responses.activate
def test_content_get_published_only(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    runner.invoke(cli, ["content", "get", "10", "--published"])

    api_call = [c for c in responses.calls if "AIPage/Get" in c.request.url][0]
    assert api_call.request.params["includeDraft"] == "false"


@responses.activate
def test_content_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)
    output_file = tmp_path / "content.json"

    result = runner.invoke(cli, ["content", "get", "10", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["page_id"] == 10
    assert len(data["components"]) == 1


@responses.activate
def test_content_get_locale(runner, mock_config):
    mock_homepage()
    locale_response = {**SAMPLE_API_RESPONSE, "locale": "fr-FR"}
    responses.add(responses.GET, GET_PAGE_URL, json=locale_response, status=200)

    result = runner.invoke(cli, ["content", "get", "10", "--locale", "fr-FR"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["locale"] == "fr-FR"


@responses.activate
def test_content_update_from_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 4},
        status=200,
    )

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps({
        "components": SAMPLE_COMPONENTS,
        "styles": SAMPLE_STYLES,
    }))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file)])

    assert result.exit_code == 0
    assert "Content updated for page 10" in result.output
    assert "version 4" in result.output

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 10
    assert sent_body["locale"] == "en-US"
    # ContentJSON should be a JSON string, not a raw object
    parsed_components = json.loads(sent_body["contentJSON"])
    assert len(parsed_components) == 1


@responses.activate
def test_content_update_with_version(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 5},
        status=200,
    )

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps({"components": [], "styles": []}))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file), "--version", "4"])

    assert result.exit_code == 0

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["expectedVersion"] == 4


@responses.activate
def test_content_update_json_output(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 4},
        status=200,
    )

    content_file = tmp_path / "content.json"
    content_file.write_text(json.dumps({"components": SAMPLE_COMPONENTS, "styles": SAMPLE_STYLES}))

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(content_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"
    assert data["page_id"] == 10


@responses.activate
def test_content_update_no_input(runner, mock_config):
    result = runner.invoke(cli, ["content", "update", "10"])
    assert result.exit_code != 0


@responses.activate
def test_content_update_invalid_json(runner, mock_config, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json at all {{{")

    result = runner.invoke(cli, ["content", "update", "10", "--file", str(bad_file)])

    assert result.exit_code == 1


@responses.activate
def test_content_get_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json={"Message": "Page not found"}, status=404)

    result = runner.invoke(cli, ["content", "get", "999"])

    assert result.exit_code == 1


@responses.activate
def test_content_get_null_response(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=None, status=200)

    result = runner.invoke(cli, ["content", "get", "5"])

    assert result.exit_code == 1


@responses.activate
def test_content_publish(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        PUBLISH_PAGE_URL,
        json={"pageId": 10, "isPublished": True},
        status=200,
    )

    result = runner.invoke(cli, ["content", "publish", "10"])

    assert result.exit_code == 0
    assert "Page 10 published" in result.output


@responses.activate
def test_content_publish_json(runner, mock_config):
    mock_homepage()
    responses.add(
        responses.POST,
        PUBLISH_PAGE_URL,
        json={"pageId": 10, "isPublished": True},
        status=200,
    )

    result = runner.invoke(cli, ["content", "publish", "10", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "published"
    assert data["page_id"] == 10


@responses.activate
def test_content_publish_sends_locale(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, PUBLISH_PAGE_URL, json={}, status=200)

    runner.invoke(cli, ["content", "publish", "10", "--locale", "fr-FR"])

    post_call = [c for c in responses.calls if "AIPage/Publish" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 10
    assert sent_body["locale"] == "fr-FR"


# --- diff command tests ---

DRAFT_COMPONENTS = [
    {"type": "text", "content": "Hello", "attributes": {"id": "abc12"}},
    {"type": "image", "content": "", "attributes": {"id": "img01"}},
]
PUBLISHED_COMPONENTS = [
    {"type": "text", "content": "Hello", "attributes": {"id": "abc12"}},
    {"type": "image", "content": "", "attributes": {"id": "img01"}},
]
DRAFT_COMPONENTS_WITH_ADDITION = [
    {"type": "text", "content": "Hello", "attributes": {"id": "abc12"}},
    {"type": "image", "content": "", "attributes": {"id": "img01"}},
    {"type": "text", "content": "New block", "attributes": {"id": "new99"}},
]


def _make_diff_response(
    components: list,
    styles: list | None = None,
    version: int = 3,
    is_published: bool = True,
) -> dict:
    if styles is None:
        styles = SAMPLE_STYLES
    return {
        "pageId": 34,
        "contentJSON": json.dumps(components),
        "styleJSON": json.dumps(styles),
        "version": version,
        "isPublished": is_published,
    }


@responses.activate
def test_content_diff_no_changes(runner, mock_config):
    mock_homepage()
    same_response = _make_diff_response(PUBLISHED_COMPONENTS, version=3)
    responses.add(responses.GET, GET_PAGE_URL, json=same_response, status=200)
    responses.add(responses.GET, GET_PAGE_URL, json=same_response, status=200)

    result = runner.invoke(cli, ["content", "diff", "34"])

    assert result.exit_code == 0
    assert "No unpublished changes." in result.output
    assert "Page 34:" in result.output


@responses.activate
def test_content_diff_with_changes(runner, mock_config):
    mock_homepage()
    draft = _make_diff_response(DRAFT_COMPONENTS_WITH_ADDITION, version=5, is_published=False)
    published = _make_diff_response(PUBLISHED_COMPONENTS, version=3)
    responses.add(responses.GET, GET_PAGE_URL, json=draft, status=200)
    responses.add(responses.GET, GET_PAGE_URL, json=published, status=200)

    result = runner.invoke(cli, ["content", "diff", "34"])

    assert result.exit_code == 0
    assert "Has unpublished changes." in result.output
    assert "draft version 5 vs published version 3" in result.output
    assert "Added:" in result.output
    assert "new99" in result.output
    assert "Removed:   (none)" in result.output


@responses.activate
def test_content_diff_json(runner, mock_config):
    mock_homepage()
    draft = _make_diff_response(DRAFT_COMPONENTS_WITH_ADDITION, version=5, is_published=False)
    published = _make_diff_response(PUBLISHED_COMPONENTS, version=3)
    responses.add(responses.GET, GET_PAGE_URL, json=draft, status=200)
    responses.add(responses.GET, GET_PAGE_URL, json=published, status=200)

    result = runner.invoke(cli, ["content", "diff", "34", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["page_id"] == 34
    assert data["published_version"] == 3
    assert data["draft_version"] == 5
    assert data["has_changes"] is True
    assert data["components"]["published_count"] == 2
    assert data["components"]["draft_count"] == 3
    assert "new99" in data["components"]["added"]
    assert data["components"]["removed"] == []
    assert data["styles"]["changed"] is False


@responses.activate
def test_content_diff_no_published_version(runner, mock_config):
    mock_homepage()
    draft = _make_diff_response(DRAFT_COMPONENTS, version=1, is_published=False)
    responses.add(responses.GET, GET_PAGE_URL, json=draft, status=200)
    responses.add(
        responses.GET,
        GET_PAGE_URL,
        body="null",
        content_type="application/json",
        status=200,
    )

    result = runner.invoke(cli, ["content", "diff", "34"])

    assert result.exit_code == 1
    assert "no published version" in result.output


# --- snapshot command tests ---


@responses.activate
def test_content_snapshot_default_location(runner, mock_config, tmp_path):
    """Default snapshot path lives under ~/.vanjaro-cli/snapshots/<host>/.

    The patched CONFIG_DIR points at tmp_path, so the snapshot file
    must land there — never in the working directory.
    """
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)

    cwd_before = set(Path.cwd().iterdir())

    result = runner.invoke(cli, ["content", "snapshot", "10"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "Snapshot saved to" in result.output
    assert "page 10" in result.output
    assert "version 3" in result.output

    # CRITICAL: snapshot must NOT have been written to the working directory.
    cwd_after = set(Path.cwd().iterdir())
    new_in_cwd = cwd_after - cwd_before
    assert not any(p.name.startswith("page-10-v3-") for p in new_in_cwd), (
        f"Snapshot leaked into cwd: {[p.name for p in new_in_cwd]}"
    )

    # The snapshot file should exist under tmp_path/.vanjaro-cli/snapshots/<host>/.
    snapshot_root = tmp_path / ".vanjaro-cli" / "snapshots"
    assert snapshot_root.exists(), "snapshot root directory was not created"
    snapshot_files = list(snapshot_root.rglob("page-10-v3-*.json"))
    assert len(snapshot_files) == 1, f"expected exactly one snapshot, got {snapshot_files}"

    snapshot_data = json.loads(snapshot_files[0].read_text())
    assert snapshot_data["snapshot"]["page_id"] == 10
    assert snapshot_data["snapshot"]["version"] == 3
    assert snapshot_data["snapshot"]["locale"] == "en-US"
    assert snapshot_data["snapshot"]["base_url"] == BASE_URL
    assert "created_at" in snapshot_data["snapshot"]
    assert snapshot_data["components"] == SAMPLE_COMPONENTS
    assert snapshot_data["styles"] == SAMPLE_STYLES


@responses.activate
def test_content_snapshot_custom_output(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)
    output_file = tmp_path / "my-snapshot.json"

    result = runner.invoke(cli, ["content", "snapshot", "10", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()

    snapshot_data = json.loads(output_file.read_text())
    assert snapshot_data["snapshot"]["page_id"] == 10
    assert snapshot_data["snapshot"]["version"] == 3
    assert snapshot_data["components"] == SAMPLE_COMPONENTS
    assert snapshot_data["styles"] == SAMPLE_STYLES


@responses.activate
def test_content_snapshot_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_PAGE_URL, json=SAMPLE_API_RESPONSE, status=200)
    output_file = tmp_path / "snapshot.json"

    result = runner.invoke(cli, ["content", "snapshot", "10", "--output", str(output_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"
    assert data["page_id"] == 10
    assert data["version"] == 3
    assert data["file"] == str(output_file)


# --- rollback command tests ---


@responses.activate
def test_content_rollback(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 6},
        status=200,
    )

    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps({
        "snapshot": {
            "page_id": 10,
            "version": 3,
            "locale": "en-US",
            "created_at": "2026-04-02T19:30:00+00:00",
            "base_url": BASE_URL,
        },
        "components": SAMPLE_COMPONENTS,
        "styles": SAMPLE_STYLES,
    }))

    result = runner.invoke(cli, ["content", "rollback", "10", "--file", str(snapshot_file)])

    assert result.exit_code == 0
    assert "Page 10 restored from snapshot" in result.output
    assert "version 6" in result.output

    post_call = [c for c in responses.calls if "AIPage/Update" in c.request.url][0]
    sent_body = json.loads(post_call.request.body)
    assert sent_body["pageId"] == 10
    assert sent_body["locale"] == "en-US"
    parsed_components = json.loads(sent_body["contentJSON"])
    assert parsed_components == SAMPLE_COMPONENTS
    parsed_styles = json.loads(sent_body["styleJSON"])
    assert parsed_styles == SAMPLE_STYLES


@responses.activate
def test_content_rollback_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(
        responses.POST,
        UPDATE_PAGE_URL,
        json={"pageId": 10, "version": 6},
        status=200,
    )

    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps({
        "snapshot": {
            "page_id": 10,
            "version": 3,
            "locale": "en-US",
            "created_at": "2026-04-02T19:30:00+00:00",
            "base_url": BASE_URL,
        },
        "components": SAMPLE_COMPONENTS,
        "styles": SAMPLE_STYLES,
    }))

    result = runner.invoke(cli, ["content", "rollback", "10", "--file", str(snapshot_file), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "restored"
    assert data["page_id"] == 10
    assert data["version"] == 6


def test_content_rollback_missing_file(runner, mock_config, tmp_path):
    nonexistent = tmp_path / "does-not-exist.json"

    result = runner.invoke(cli, ["content", "rollback", "10", "--file", str(nonexistent)])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_content_rollback_invalid_json(runner, mock_config, tmp_path):
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("this is not valid json {{{")

    result = runner.invoke(cli, ["content", "rollback", "10", "--file", str(bad_file)])

    assert result.exit_code == 1
    assert "Invalid JSON" in result.output
