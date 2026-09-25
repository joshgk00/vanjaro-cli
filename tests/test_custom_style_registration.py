"""Styled custom-block registration must stay on the custom storage branch.

Root inspection of Vanjaro's ``BlockController.AddCustomBlock`` ->
``BlockManager.Add`` (``C:/Code/Vanjaro.Platform``) shows custom-block
storage is selected only when the POSTed ``Html`` *and* ``Css`` form fields
are both empty; a nonempty ``Css`` takes the global-block branch regardless
of ``IsGlobal``. ``_registration_form`` used to render ``item["style_json"]``
into ``Css``, so any styled custom block silently registered as a global
block. ``artifacts/test_custom_block_registration_kind_independent.py`` is
the immutable root reproduction of that request-shape defect;
``vanjaro_cli/portal/block_library.py::_registration_form`` now sends an
empty ``Css`` unconditionally and relies on ``StyleJSON``/``ContentJSON``
plus page composition's own ``render_styles`` pass to carry the styling.

The tests below run the real ``compose_project_library``/
``register_project_library``/``preview_project_library`` functions against a
stateful fake portal backend that reproduces that inspected branch choice
(and a ``FilterStyles``-equivalent id-selector match against live content
ids) rather than a client double that merely records calls -- so a
regression back to the old request shape is caught by the fake's storage
placement and read-back, not by re-asserting the fixed helper's return
value in isolation. This is offline evidence from source inspection, not
proof of the deployed server binary's behavior; an authorized live
custom-block readback is still required before this correction can be
treated as portal-verified.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from vanjaro_cli.design.models import StyleObservation, StyleProperty, StyleSet
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.portal import block_library
from vanjaro_cli.portal.block_library import (
    ADD_BLOCK,
    BlockLibraryError,
    _registration_form,
    _state_hash,
    compose_project_library,
    preview_project_library,
    register_project_library,
)
from vanjaro_cli.portal.page_composition import compose_project_pages
from vanjaro_cli.utils.grapesjs import render_styles

_FIXTURE = runpy.run_path(str(Path(__file__).resolve().parent / "test_design_planner.py"))
_document = _FIXTURE["_document"]
_feature_section = _FIXTURE["_feature_section"]
CATALOG = _FIXTURE["CATALOG"]


# ---------------------------------------------------------------------------
# Source-grounded stateful fake: branches on Html/Css like BlockManager.Add,
# and filters style rules by matching id-selectors against live content ids
# like the inspected PageManager.FilterStyle/BlockManager.FilterStyles --
# it must not blanket-strip mediaText rules the way the older global-block
# notes described for the *other*, unrelated migration path.
# ---------------------------------------------------------------------------


class _Response:
    def __init__(self, value: object) -> None:
        self._value = value

    def json(self) -> object:
        return self._value


def _content_ids(nodes: list[dict] | None) -> set[str]:
    ids: set[str] = set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node_id = node.get("attributes", {}).get("id")
        if isinstance(node_id, str) and node_id:
            ids.add(node_id)
        ids |= _content_ids(node.get("components"))
    return ids


def _filter_styles_by_content_ids(
    content_json: list[dict], style_json: list[dict]
) -> list[dict]:
    live_ids = _content_ids(content_json)
    kept: list[dict] = []
    for rule in style_json or []:
        id_selectors = [
            selector
            for selector in rule.get("selectors", [])
            if isinstance(selector, dict) and selector.get("type") == 2
        ]
        if id_selectors and not all(selector.get("name") in live_ids for selector in id_selectors):
            continue
        kept.append(rule)
    return kept


class SourceBackedBlockPortal:
    """Fake reproducing the inspected BlockManager.Add storage branch.

    ``custom_blocks`` is what ``GET LIST_BLOCKS`` (GetAllCustomBlock)
    exposes. A POST with nonempty ``Html``/``Css`` lands in
    ``global_blocks`` instead -- invisible to that same listing, exactly as
    the inspected backend's global-block branch would be.
    """

    def __init__(self) -> None:
        self.custom_blocks: list[dict[str, Any]] = []
        self.global_blocks: list[dict[str, Any]] = []
        self.posts: list[dict[str, str]] = []
        self._next_id = 0
        self._pending_concurrent: dict[str, dict[str, Any]] = {}

    def queue_concurrent_creation(
        self, name: str, *, content_json: list[dict], style_json: list[dict]
    ) -> None:
        """Simulate another actor creating ``name`` between preflight and POST."""

        self._next_id += 1
        self._pending_concurrent[name.casefold()] = {
            "ID": self._next_id,
            "Guid": f"concurrent-guid-{self._next_id}",
            "Name": name,
            "Category": "concurrent",
            "ContentJSON": json.dumps(content_json, ensure_ascii=False),
            "StyleJSON": json.dumps(style_json, ensure_ascii=False),
        }

    def get(self, path: str) -> _Response:
        assert path == block_library.LIST_BLOCKS, f"unexpected GET {path}"
        return _Response(list(self.custom_blocks))

    def post_form(self, path: str, form: dict[str, str]) -> _Response:
        assert path == ADD_BLOCK, f"unexpected POST {path}"
        self.posts.append(dict(form))
        name = form["Name"]

        pending = self._pending_concurrent.pop(name.casefold(), None)
        if pending is not None:
            self.custom_blocks.append(pending)
            return _Response({"Status": "Exist"})

        if any(row["Name"].casefold() == name.casefold() for row in self.custom_blocks):
            return _Response({"Status": "Exist"})

        self._next_id += 1
        content_json = json.loads(form["ContentJSON"])
        style_json = json.loads(form["StyleJSON"])
        row = {
            "ID": self._next_id,
            "Guid": f"guid-{self._next_id}",
            "Name": name,
            "Category": form["Category"],
            "ContentJSON": json.dumps(content_json, ensure_ascii=False),
            "StyleJSON": json.dumps(
                _filter_styles_by_content_ids(content_json, style_json), ensure_ascii=False
            ),
        }
        if form.get("Html") or form.get("Css"):
            self.global_blocks.append(row)
        else:
            self.custom_blocks.append(row)
        return _Response({"Status": "Success"})


def _write_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "templates" / "Sections"
    directory.mkdir(parents=True)
    template = {
        "name": "Styled Section",
        "category": "Sections",
        "template": {
            "type": "section",
            "attributes": {"id": "styled-section-root"},
            "components": [
                {
                    "type": "heading",
                    "attributes": {"id": "styled-section-heading"},
                    "content": "Placeholder",
                }
            ],
        },
        "styles": [],
    }
    (directory / "styled-section.json").write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path / "templates"))


def _styled_plan(
    *, key: str = "proof.section", name: str = "Styled proof block"
) -> list[object]:
    return [
        {
            "key": key,
            "template": "Styled Section",
            "name": name,
            "category": "Agency - proof",
            "overrides": {},
            "style_scope": ".proof-project .proof-section",
            "style_declarations": {
                "min-height": "520px",
                "tablet:min-height": "460px",
                "mobile:font-size": "17px",
            },
        }
    ]


# ---------------------------------------------------------------------------
# Core proof: a styled custom block registers into the custom catalog, and a
# second identical registration reuses it without another POST.
# ---------------------------------------------------------------------------


def test_styled_custom_block_creates_in_custom_catalog_and_second_registration_reuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_template(tmp_path, monkeypatch)
    plan = _styled_plan()
    backend = SourceBackedBlockPortal()
    manifest_path = tmp_path / "build/block-manifest.json"

    desired, records = register_project_library(backend, plan=plan, manifest_path=manifest_path)

    assert len(backend.posts) == 1
    form = backend.posts[0]
    # Inspect the actual POST data sent to the portal, not a mocked helper's
    # return value: the request-shape fix must survive the real call site.
    assert form["Html"] == ""
    assert form["Css"] == "", "nonempty Css selects the global-block branch on the inspected backend"
    assert json.loads(form["ContentJSON"]) == desired[0]["content_json"]
    assert json.loads(form["StyleJSON"]) == desired[0]["style_json"], "styles must not be discarded"

    assert backend.global_blocks == [], "styled block must never take the global storage branch"
    assert len(backend.custom_blocks) == 1
    assert backend.custom_blocks[0]["Name"] == desired[0]["name"]
    assert records[0]["status"] == "created"
    assert records[0]["guid"] == backend.custom_blocks[0]["Guid"]

    backend.posts.clear()
    _, resumed = register_project_library(backend, plan=plan, manifest_path=manifest_path)

    assert backend.posts == [], "an unchanged desired hash must reuse without a second POST"
    assert resumed[0]["status"] == "reused"
    assert resumed[0]["guid"] == records[0]["guid"]


# ---------------------------------------------------------------------------
# Responsive, id-targeted style rules must reach the request unstripped and
# survive an id-selector-matching backend filter (not a blanket mediaText
# strip left over from the older global-block notes).
# ---------------------------------------------------------------------------


def test_responsive_id_targeted_style_rules_survive_registration_and_backend_filtering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_template(tmp_path, monkeypatch)
    plan = _styled_plan(key="responsive.section", name="Responsive proof block")
    desired = compose_project_library(plan)
    style_json = desired[0]["style_json"]

    assert len(style_json) == 3, style_json
    by_media = {rule.get("mediaText"): rule for rule in style_json}
    assert by_media[None]["style"]["min-height"] == "520px"
    assert by_media["(max-width: 768px)"]["style"]["min-height"] == "460px"
    assert by_media["(max-width: 390px)"]["style"]["font-size"] == "17px"
    target_id = "styled-section-root"
    for rule in style_json:
        (selector,) = rule["selectors"]
        assert selector["type"] == 2 and selector["name"] == target_id, (
            "a responsive section rule must target the section's real id, not an "
            "unmatched class"
        )

    backend = SourceBackedBlockPortal()
    register_project_library(backend, plan=plan, manifest_path=tmp_path / "build/block-manifest.json")

    stored_style = json.loads(backend.custom_blocks[0]["StyleJSON"])
    assert stored_style == style_json, (
        "the id-selector-matching backend filter must keep every rule whose id "
        "is present in the registered content, including mediaText rules"
    )

    css = render_styles(stored_style)
    assert "#styled-section-root{min-height:520px}" in css
    assert "@media (max-width: 768px){#styled-section-root{min-height:460px}}" in css
    assert "@media (max-width: 390px){#styled-section-root{font-size:17px}}" in css


# ---------------------------------------------------------------------------
# Fail-closed: if the request shape ever regresses to the old (nonempty Css)
# form, registration must raise -- never fabricate a "created" record from a
# row the custom-block listing never actually exposes.
# ---------------------------------------------------------------------------


def test_regression_to_nonempty_css_fails_closed_instead_of_fabricating_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_template(tmp_path, monkeypatch)
    plan = _styled_plan(key="regression.section", name="Regression proof block")

    def _pre_fix_form(item: dict[str, Any], portal_name: str) -> dict[str, str]:
        # The exact defect this correction fixes: styled Css is nonempty.
        return {
            "Name": portal_name,
            "Category": item["category"],
            "Html": "",
            "Css": render_styles(item["style_json"]),
            "IsGlobal": "false",
            "ContentJSON": json.dumps(item["content_json"], ensure_ascii=False),
            "StyleJSON": json.dumps(item["style_json"], ensure_ascii=False),
        }

    monkeypatch.setattr(block_library, "_registration_form", _pre_fix_form)
    backend = SourceBackedBlockPortal()

    with pytest.raises(BlockLibraryError, match="did not expose one unambiguous row"):
        register_project_library(backend, plan=plan, manifest_path=tmp_path / "build/block-manifest.json")

    assert backend.posts, "the POST must still have been attempted"
    assert backend.posts[0]["Css"], "sanity check: the regressed form actually sent a nonempty Css"
    assert backend.global_blocks and not backend.custom_blocks, (
        "a nonempty Css must be routed to the global branch, which GetAllCustomBlock never lists"
    )


def test_concurrent_creation_with_different_content_fails_closed_on_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_template(tmp_path, monkeypatch)
    plan = _styled_plan(key="race.section", name="Race proof block")
    desired = compose_project_library(plan)
    backend = SourceBackedBlockPortal()
    backend.queue_concurrent_creation(
        desired[0]["name"],
        content_json=[{"type": "section", "attributes": {"id": "someone-elses-root"}, "components": []}],
        style_json=[],
    )

    with pytest.raises(BlockLibraryError, match="concurrent name collision"):
        register_project_library(backend, plan=plan, manifest_path=tmp_path / "build/block-manifest.json")

    assert len(backend.posts) == 1
    assert backend.custom_blocks and backend.custom_blocks[0]["Name"] == desired[0]["name"]


# ---------------------------------------------------------------------------
# Preview must reflect the fixed custom-branch request shape without ever
# mutating the portal.
# ---------------------------------------------------------------------------


def test_preview_reflects_fixed_custom_branch_request_shape_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_template(tmp_path, monkeypatch)
    plan = _styled_plan(key="preview.section", name="Preview proof block")
    item = compose_project_library(plan)[0]
    expected_form = _registration_form(item, item["name"])
    assert expected_form["Html"] == ""
    assert expected_form["Css"] == ""

    backend = SourceBackedBlockPortal()
    result = preview_project_library(
        backend, plan=plan, manifest_path=tmp_path / "build/block-manifest.json"
    )

    assert backend.posts == []
    assert result["to_create"] == 1
    planned = result["blocks"][0]
    assert planned["endpoint"] == ADD_BLOCK
    assert planned["payload_fingerprint"] == _state_hash(expected_form)
    assert [operation["kind"] for operation in planned["operations"]] == [
        "local_checkpoint",
        "portal_request",
        "portal_readback",
        "local_checkpoint",
    ]


# ---------------------------------------------------------------------------
# Visitor-facing page CSS must survive even though the registration request
# now always sends an empty Css field -- page composition renders style_json
# into visitor HTML independently of the block's registration form.
# ---------------------------------------------------------------------------


def test_visitor_facing_page_css_survives_despite_empty_registration_css_field(
    tmp_path: Path,
) -> None:
    section = _feature_section().model_copy(
        update={
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.MIN_HEIGHT, value="523px")]
            )
        }
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    library = emit_library_plan(plan)
    composed = compose_project_library(library)

    backend = SourceBackedBlockPortal()
    desired, _ = register_project_library(
        backend, plan=library, manifest_path=tmp_path / "build/block-manifest.json"
    )
    assert backend.posts[0]["Html"] == ""
    assert backend.posts[0]["Css"] == ""

    pages = compose_project_pages(
        document, desired, {"entries": []}, project_id="registration-css-proof", isolated=True
    )
    page = pages[0]
    assert "523px" in page["content_html"], "accepted style must still reach visitor-facing HTML"
    assert page["content_html"].startswith("<style>")
