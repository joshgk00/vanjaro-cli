"""Tests for vanjaro global-blocks commands."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import responses

from vanjaro_cli.cli import cli
from tests.conftest import BASE_URL, mock_homepage

LIST_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/List"
GET_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Get"
# Create hits the core Block endpoint (same one the admin UI uses) — the
# VanjaroAI/AIGlobalBlock/Create endpoint stores the record but doesn't
# register it for render-time expansion.
CREATE_URL = f"{BASE_URL}/API/Vanjaro/Block/AddCustomBlock"
UPDATE_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Update"
PUBLISH_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Publish"
DELETE_URL = f"{BASE_URL}/API/VanjaroAI/AIGlobalBlock/Delete"


def _form_fields(request) -> dict[str, str]:
    """Decode the last form-encoded POST body into a flat dict."""
    parsed = parse_qs(request.body, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}

SAMPLE_BLOCKS = [
    {
        "id": 1,
        "guid": "20020077-89f8-468f-a488-017421ce5a0b",
        "name": "Header",
        "category": "site",
        "isPublished": True,
        "version": 1,
        "updatedOn": "2026-04-02T12:16:35.05Z",
    },
    {
        "id": 2,
        "guid": "fe37ff48-2c99-4201-85fc-913cac94914d",
        "name": "Footer",
        "category": "site",
        "isPublished": True,
        "version": 1,
        "updatedOn": "2026-04-02T12:16:35.087Z",
    },
]

SAMPLE_BLOCK_DETAIL = {
    "id": 1,
    "guid": "20020077-89f8-468f-a488-017421ce5a0b",
    "name": "Header",
    "category": "site",
    "version": 1,
    "isPublished": True,
    "contentJSON": [{"type": "section", "components": []}],
    "styleJSON": [{"selectors": [".header"], "style": {"color": "blue"}}],
}


@responses.activate
def test_global_blocks_list(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"total": 2, "blocks": SAMPLE_BLOCKS}, status=200)

    result = runner.invoke(cli, ["global-blocks", "list"])

    assert result.exit_code == 0
    assert "Header" in result.output
    assert "Footer" in result.output


@responses.activate
def test_global_blocks_list_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"total": 2, "blocks": SAMPLE_BLOCKS}, status=200)

    result = runner.invoke(cli, ["global-blocks", "list", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["name"] == "Header"
    assert data[0]["is_published"] is True
    assert data[1]["guid"] == "fe37ff48-2c99-4201-85fc-913cac94914d"


@responses.activate
def test_global_blocks_list_empty(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"total": 0, "blocks": []}, status=200)

    result = runner.invoke(cli, ["global-blocks", "list"])

    assert result.exit_code == 0
    assert "No global blocks found." in result.output


SAMPLE_CREATE_RESPONSE = {
    "Status": "Success",
    "Guid": "abc12345-6789-0000-1111-222233334444",
}

SAMPLE_BLOCK_FILE_CONTENT = {
    "contentJSON": [{"type": "section", "components": [{"type": "heading", "content": "Call to Action"}]}],
    "styleJSON": [{"selectors": [".cta"], "style": {"background": "#C75B8E"}}],
}


@responses.activate
def test_global_blocks_create(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json=SAMPLE_CREATE_RESPONSE, status=201)

    block_file = tmp_path / "cta.json"
    block_file.write_text(json.dumps(SAMPLE_BLOCK_FILE_CONTENT))

    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--name", "CTA Banner",
        "--category", "marketing",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    assert "Created global block 'CTA Banner'" in result.output
    assert "abc12345" in result.output

    fields = _form_fields(responses.calls[-1].request)
    assert fields["Name"] == "CTA Banner"
    assert fields["Category"] == "marketing"
    assert fields["IsGlobal"] == "true"
    # Server requires a non-empty Html to register the block as global — an
    # empty Html causes it to land in the custom-block table instead.
    assert fields["Html"], "Html must be rendered from the component tree"
    assert "Call to Action" in fields["Html"]
    assert json.loads(fields["ContentJSON"])[0]["type"] == "section"
    assert json.loads(fields["StyleJSON"])[0]["selectors"] == [".cta"]


@responses.activate
def test_global_blocks_create_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json=SAMPLE_CREATE_RESPONSE, status=201)

    block_file = tmp_path / "cta.json"
    block_file.write_text(json.dumps(SAMPLE_BLOCK_FILE_CONTENT))

    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--name", "CTA Banner",
        "--file", str(block_file),
        "--json",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "created"
    assert data["name"] == "CTA Banner"
    assert data["guid"] == "abc12345-6789-0000-1111-222233334444"
    assert data["category"] == "general"


@responses.activate
def test_global_blocks_create_duplicate_name(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json={"Status": "Exist"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({"contentJSON": [], "styleJSON": []}))

    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--name", "Header",
        "--file", str(block_file),
    ])

    assert result.exit_code == 1
    assert "already exists" in result.output


@responses.activate
def test_global_blocks_create_snake_case_keys(runner, mock_config, tmp_path):
    """Accepts snake_case keys (content_json) in addition to camelCase."""
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json=SAMPLE_CREATE_RESPONSE, status=201)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "content_json": [{"type": "section"}],
        "style_json": [],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--name", "Test Block",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    fields = _form_fields(responses.calls[-1].request)
    assert json.loads(fields["ContentJSON"]) == [{"type": "section"}]


@responses.activate
def test_global_blocks_create_scaffold_format(runner, mock_config, tmp_path):
    """Accepts scaffold output format with components/styles keys."""
    mock_homepage()
    responses.add(responses.POST, CREATE_URL, json=SAMPLE_CREATE_RESPONSE, status=201)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "components": [{"type": "section", "components": []}],
        "styles": [],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--name", "Scaffolded Block",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    fields = _form_fields(responses.calls[-1].request)
    assert json.loads(fields["ContentJSON"]) == [{"type": "section", "components": []}]


def test_global_blocks_create_invalid_json_file(runner, mock_config, tmp_path):
    block_file = tmp_path / "bad.json"
    block_file.write_text("not json at all {{{")

    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--name", "Bad Block",
        "--file", str(block_file),
    ])

    assert result.exit_code == 1


def test_global_blocks_create_missing_required_options(runner, mock_config, tmp_path):
    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({"contentJSON": []}))

    # Missing --name
    result = runner.invoke(cli, [
        "global-blocks", "create",
        "--file", str(block_file),
    ])
    assert result.exit_code != 0
    assert "Missing" in result.output or "required" in result.output.lower()


@responses.activate
def test_global_blocks_get(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)

    result = runner.invoke(cli, ["global-blocks", "get", "20020077-89f8-468f-a488-017421ce5a0b"])

    assert result.exit_code == 0
    assert "Header" in result.output
    assert "20020077-89f8-468f-a488-017421ce5a0b" in result.output
    assert "site" in result.output


@responses.activate
def test_global_blocks_get_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)

    result = runner.invoke(cli, ["global-blocks", "get", "20020077-89f8-468f-a488-017421ce5a0b", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "Header"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"
    assert len(data["content_json"]) == 1
    assert data["content_json"][0]["type"] == "section"


@responses.activate
def test_global_blocks_get_to_file(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json=SAMPLE_BLOCK_DETAIL, status=200)
    output_file = tmp_path / "block.json"

    result = runner.invoke(cli, ["global-blocks", "get", "20020077-89f8-468f-a488-017421ce5a0b", "--output", str(output_file)])

    assert result.exit_code == 0
    assert output_file.exists()
    data = json.loads(output_file.read_text())
    assert data["name"] == "Header"
    assert "Block written to" in result.output


@responses.activate
def test_global_blocks_get_not_found(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, GET_URL, json={"Message": "Block not found"}, status=404)

    result = runner.invoke(cli, ["global-blocks", "get", "nonexistent-guid"])

    assert result.exit_code == 1


@responses.activate
def test_global_blocks_api_error(runner, mock_config):
    mock_homepage()
    responses.add(responses.GET, LIST_URL, json={"Message": "Internal server error"}, status=500)

    result = runner.invoke(cli, ["global-blocks", "list"])

    assert result.exit_code == 1


@responses.activate
def test_global_blocks_update(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "content_json": [{"type": "section", "components": []}],
        "style_json": [{"selectors": [".header"], "style": {"color": "red"}}],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "update", "20020077-89f8-468f-a488-017421ce5a0b",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    assert "updated" in result.output

    request_body = json.loads(responses.calls[-1].request.body)
    assert request_body["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"
    # AIGlobalBlock/Update binds these as strings; raw arrays cause HTTP 500
    assert json.loads(request_body["contentJSON"]) == [{"type": "section", "components": []}]
    assert json.loads(request_body["styleJSON"]) == [{"selectors": [".header"], "style": {"color": "red"}}]


@responses.activate
def test_global_blocks_update_accepts_components_shape(runner, mock_config, tmp_path):
    """build-global emits {components, styles} — update must accept it."""
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "components": [{"type": "section", "components": []}],
        "styles": [],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "update", "20020077-89f8-468f-a488-017421ce5a0b",
        "--file", str(block_file),
    ])

    assert result.exit_code == 0
    request_body = json.loads(responses.calls[-1].request.body)
    assert json.loads(request_body["contentJSON"]) == [{"type": "section", "components": []}]
    # Wrapper expansion renders stored Html — update must re-render it or the
    # server keeps the stale version and live pages never change
    assert "<section" in request_body["html"]


@responses.activate
def test_global_blocks_update_json(runner, mock_config, tmp_path):
    mock_homepage()
    responses.add(responses.POST, UPDATE_URL, json={"status": "ok"}, status=200)

    block_file = tmp_path / "block.json"
    block_file.write_text(json.dumps({
        "contentJSON": [{"type": "div"}],
        "styleJSON": [],
    }))

    result = runner.invoke(cli, [
        "global-blocks", "update", "20020077-89f8-468f-a488-017421ce5a0b",
        "--file", str(block_file), "--json",
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "updated"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


@responses.activate
def test_global_blocks_publish(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, PUBLISH_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "publish", "20020077-89f8-468f-a488-017421ce5a0b"])

    assert result.exit_code == 0
    assert "published" in result.output

    request_body = json.loads(responses.calls[-1].request.body)
    assert request_body["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


@responses.activate
def test_global_blocks_publish_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, PUBLISH_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "publish", "20020077-89f8-468f-a488-017421ce5a0b", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


@responses.activate
def test_global_blocks_delete_with_force(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "delete", "20020077-89f8-468f-a488-017421ce5a0b", "--force"])

    assert result.exit_code == 0
    assert "deleted" in result.output

    request_body = json.loads(responses.calls[-1].request.body)
    assert request_body["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


def test_global_blocks_delete_abort(runner, mock_config):
    result = runner.invoke(cli, ["global-blocks", "delete", "20020077-89f8-468f-a488-017421ce5a0b"], input="n\n")

    assert result.exit_code != 0


@responses.activate
def test_global_blocks_delete_json(runner, mock_config):
    mock_homepage()
    responses.add(responses.POST, DELETE_URL, json={"status": "ok"}, status=200)

    result = runner.invoke(cli, ["global-blocks", "delete", "20020077-89f8-468f-a488-017421ce5a0b", "--force", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "deleted"
    assert data["guid"] == "20020077-89f8-468f-a488-017421ce5a0b"


def test_header_block_applies_band_colors():
    from vanjaro_cli.migration.global_blocks import build_header_block

    content = {
        "images": [{"src": "/logo.png", "alt": "Logo"}],
        "list_items": ["Home", "About"],
        "background_color": "rgb(20, 20, 20)",
        "text_color": "rgb(255, 255, 255)",
    }

    block = build_header_block(content)

    style = block["components"][0]["attributes"]["style"]
    assert "background-color:rgb(20, 20, 20);" in style
    assert "color:rgb(255, 255, 255);" in style


def test_footer_block_dark_band_gets_white_text():
    from vanjaro_cli.migration.global_blocks import build_footer_block

    content = {
        "paragraphs": ["Copyright 2026"],
        "background_color": "#1a1a1a",
    }

    block = build_footer_block(content)

    style = block["components"][0]["attributes"]["style"]
    assert "background-color:#1a1a1a;" in style
    assert "color:#ffffff;" in style


def test_blocks_without_band_colors_have_no_style():
    from vanjaro_cli.migration.global_blocks import build_footer_block

    block = build_footer_block({"paragraphs": ["Copyright"]})

    assert "style" not in block["components"][0].get("attributes", {})


def test_footer_block_includes_social_and_copyright_rows():
    from vanjaro_cli.migration.global_blocks import build_footer_block

    content = {
        "paragraphs": ["We make websites."],
        "social_links": [
            {"label": "Facebook", "href": "https://facebook.com/cmw"},
            {"label": "Twitter", "href": "https://twitter.com/cmw"},
        ],
        "copyright_text": "Copyright 2026 by Clicks & Mortar Websites",
        "links": [
            {"text": "Privacy Statement", "href": "https://example.com/privacy"},
            {"text": "Terms Of Use", "href": "https://example.com/terms"},
            {"text": "Home", "href": "/"},
        ],
    }

    block = build_footer_block(content)

    rendered = str(block)
    assert "Facebook" in rendered
    assert "https://twitter.com/cmw" in rendered
    assert "Copyright 2026 by Clicks & Mortar Websites" in rendered
    assert "Privacy Statement" in rendered
    assert "Terms Of Use" in rendered
    assert "'Home'" not in rendered.replace('"', "'").split("copyright")[-1]


def test_footer_block_without_social_or_copyright_has_no_extra_rows():
    from vanjaro_cli.migration.global_blocks import build_footer_block

    block = build_footer_block({"paragraphs": ["Copyright-free blurb"]})

    rendered = str(block)
    assert "border-top" not in rendered
    assert "target" not in rendered


def test_footer_with_only_copyright_has_no_placeholder():
    """A footer that has just a copyright line must not show the empty placeholder."""
    from vanjaro_cli.migration.global_blocks import build_footer_block

    block = build_footer_block({
        "copyright_text": "Copyright 2026 by Oasis Advisors",
        "links": [{"text": "Privacy Statement", "href": "/privacy"}],
        "background_color": "rgb(34, 44, 54)",
    })

    rendered = str(block)
    assert "no content captured" not in rendered
    assert "Copyright 2026 by Oasis Advisors" in rendered


def test_truly_empty_footer_still_gets_placeholder():
    from vanjaro_cli.migration.global_blocks import build_footer_block

    block = build_footer_block({})

    assert "no content captured" in str(block)


# --- Fix A: default theme-style classes on _heading / _text ---

import re

_HEAD_STYLE = re.compile(r"\bhead-style-\d+\b")
_PARA_STYLE = re.compile(r"\bparagraph-style-\d+\b")


def _class_names(component: dict) -> list[str]:
    return [c["name"] for c in component.get("classes", [])]


def test_heading_default_carries_head_style_class():
    from vanjaro_cli.migration.global_blocks import _heading

    names = _class_names(_heading("Title", tag="h5"))

    assert "vj-heading" in names
    assert any(_HEAD_STYLE.fullmatch(n) for n in names)


def test_heading_default_with_extra_classes_still_gets_style():
    from vanjaro_cli.migration.global_blocks import _heading

    names = _class_names(_heading("Title", tag="h5", extra_classes=["mb-3"]))

    assert "mb-3" in names
    assert any(_HEAD_STYLE.fullmatch(n) for n in names)


def test_heading_does_not_double_add_explicit_head_style():
    from vanjaro_cli.migration.global_blocks import _heading

    names = _class_names(_heading("Title", tag="h5", extra_classes=["head-style-5", "mb-0"]))

    assert [n for n in names if n.startswith("head-style-")] == ["head-style-5"]


def test_text_default_carries_paragraph_style_class():
    from vanjaro_cli.migration.global_blocks import _text

    names = _class_names(_text("Body copy"))

    assert "vj-text" in names
    assert any(_PARA_STYLE.fullmatch(n) for n in names)


def test_text_default_with_extra_classes_still_gets_style():
    from vanjaro_cli.migration.global_blocks import _text

    names = _class_names(_text("Copyright 2026", extra_classes=["d-inline", "me-3"]))

    assert "d-inline" in names
    assert any(_PARA_STYLE.fullmatch(n) for n in names)


def test_text_does_not_double_add_explicit_paragraph_style():
    from vanjaro_cli.migration.global_blocks import _text

    names = _class_names(_text("Caption", extra_classes=["paragraph-style-2", "text-muted"]))

    assert [n for n in names if n.startswith("paragraph-style-")] == ["paragraph-style-2"]


def test_footer_headings_and_texts_all_theme_styled():
    """Every .vj-heading / .vj-text a real footer emits must carry a style class."""
    from vanjaro_cli.migration.global_blocks import build_footer_block

    block = build_footer_block({
        "headings": ["Services", "Company"],
        "list_items": ["SEO", "Design", "About", "Careers"],
        "paragraphs": ["We build sites."],
        "copyright_text": "Copyright 2026",
    })
    rendered = str(block)

    assert "head-style-" in rendered
    assert "paragraph-style-" in rendered


# --- Fix B: CSS-only hamburger for the static-nav header ---


def test_static_nav_header_emits_toggle_input_and_label():
    from vanjaro_cli.migration.global_blocks import build_header_block

    block = build_header_block(
        {"images": [{"src": "/logo.png", "alt": "Logo"}], "list_items": ["Home", "About"]},
        static_nav=True,
    )
    rendered = str(block)

    assert "kts-nav-toggle" in rendered
    assert "'type': 'checkbox'" in rendered
    assert "'for': 'kts-nav-toggle'" in rendered
    assert "kts-nav-links" in rendered


def test_static_nav_header_keeps_toggle_css_out_of_block_styles():
    # The styleJSON store strips @media/combinator rules on save, so the toggle
    # CSS must not ride in the block styles — it ships via portal.css instead.
    from vanjaro_cli.migration.global_blocks import build_header_block
    from vanjaro_cli.utils.grapesjs import render_styles

    block = build_header_block(
        {"images": [{"src": "/logo.png", "alt": "Logo"}], "list_items": ["Home", "About"]},
        static_nav=True,
    )
    css = render_styles(block["styles"])

    assert "kts-nav-toggle" not in css
    assert "@media" not in css


def test_nav_toggle_portal_css_has_media_query_and_combinator():
    from vanjaro_cli.migration.global_blocks import NAV_TOGGLE_PORTAL_CSS

    assert "@media (max-width: 992px)" in NAV_TOGGLE_PORTAL_CSS
    assert "#kts-nav-toggle:checked ~ .kts-nav-links" in NAV_TOGGLE_PORTAL_CSS
    assert ".kts-nav-toggle { display: none; }" in NAV_TOGGLE_PORTAL_CSS


def test_menu_nav_header_has_no_hamburger():
    from vanjaro_cli.migration.global_blocks import build_header_block

    block = build_header_block(
        {"images": [{"src": "/logo.png", "alt": "Logo"}], "list_items": ["Home", "About"]},
        static_nav=False,
    )
    rendered = str(block)

    assert "kts-nav-toggle" not in rendered
