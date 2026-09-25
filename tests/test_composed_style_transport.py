"""Scoped-style transport: accepted CompositionPlan CSS must actually reach
composed GrapesJS output through the real emit_library_plan ->
compose_project_library -> compose_project_pages path, not merely be
reported in the plan.

Reuses the maintained feature-section fixture from test_design_planner.py
(same technique as the immutable root regression in
artifacts/test_composed_style_retention_independent.py) so these tests
exercise the actual planner/template catalog, not a synthetic stand-in.
"""

from __future__ import annotations

import copy
import json
import runpy
from pathlib import Path

import pytest

from vanjaro_cli.design.models import (
    BreakpointName,
    EvidenceStatus,
    ResponsiveObservation,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.planner import emit_library_plan, plan_design_document
from vanjaro_cli.portal.block_library import BlockLibraryError, compose_project_library
from vanjaro_cli.portal.page_composition import compose_project_pages
from vanjaro_cli.utils.grapesjs import render_styles

_FIXTURE = runpy.run_path(str(Path(__file__).resolve().parent / "test_design_planner.py"))
_feature_section = _FIXTURE["_feature_section"]
_document = _FIXTURE["_document"]
CATALOG = _FIXTURE["CATALOG"]

_TABLET_MEDIA = "(max-width: 768px)"
_MOBILE_MEDIA = "(max-width: 390px)"


def _styled_section(
    *,
    section_id: str,
    desktop: str = "720px",
    tablet: str = "620px",
    mobile: str = "520px",
) -> object:
    section = _feature_section(
        section_id=section_id,
        element_prefix=f"{section_id}-el",
        group_id=f"{section_id}-cards",
        item_prefix=f"{section_id}-card",
    )
    return section.model_copy(
        update={
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.FONT_SIZE, value=desktop)]
            ),
            "responsive": [
                ResponsiveObservation(
                    breakpoint=BreakpointName.TABLET,
                    viewport=Viewport(width=768, height=1024),
                    status=EvidenceStatus.OBSERVED,
                    style=StyleSet(
                        observations=[
                            StyleObservation(property=StyleProperty.FONT_SIZE, value=tablet)
                        ]
                    ),
                ),
                ResponsiveObservation(
                    breakpoint=BreakpointName.MOBILE,
                    viewport=Viewport(width=390, height=844),
                    status=EvidenceStatus.OBSERVED,
                    style=StyleSet(
                        observations=[
                            StyleObservation(property=StyleProperty.FONT_SIZE, value=mobile)
                        ]
                    ),
                ),
            ],
        }
    )


def _multi_section_document(*sections: object) -> object:
    document = _document(sections[0])
    page = document.pages[0].model_copy(update={"sections": list(sections)})
    return document.model_copy(update={"pages": [page]})


def _compose(document: object) -> tuple[object, list[dict], list[dict]]:
    plan = plan_design_document(document, catalog=CATALOG)
    library = emit_library_plan(plan)
    composed = compose_project_library(library)
    return plan, library, composed


def _build_pages(document: object, composed: list[dict]) -> list[dict]:
    return compose_project_pages(
        document,
        composed,
        {"entries": []},
        project_id="agency-proj",
        isolated=False,
        asset_records=[],
    )


def _all_ids(component: dict) -> set[str]:
    found = set()
    attr_id = component.get("attributes", {}).get("id")
    if isinstance(attr_id, str) and attr_id:
        found.add(attr_id)
    for child in component.get("components", []) or []:
        found |= _all_ids(child)
    return found


def _id_selector_names(styles: list[dict]) -> set[str]:
    names = set()
    for rule in styles:
        for selector in rule.get("selectors", []):
            if isinstance(selector, dict) and selector.get("type") == 2:
                names.add(selector["name"])
    return names


def _rule_for(styles: list[dict], *, media: str | None) -> dict | None:
    for rule in styles:
        if rule.get("mediaText") == media or (media is None and "mediaText" not in rule):
            return rule
    return None


# ---------------------------------------------------------------------------
# Root-regression extension: survives compose_project_pages, selectors match
# the rendered tree, and the effective CSS lands in contentHtml.
# ---------------------------------------------------------------------------


def test_accepted_scoped_style_reaches_content_html_with_a_matching_selector() -> None:
    section = _styled_section(section_id="home.services", desktop="19.123px", tablet="19.123px", mobile="19.123px")
    document = _document(section)
    plan, library, composed = _compose(document)

    entry = plan.entries[0]
    assert not entry.match.blocking
    assert entry.scoped_css["font-size"] == "19.123px"
    assert library[0]["style_declarations"]["font-size"] == "19.123px"

    block = composed[0]
    css = render_styles(block["style_json"])
    assert "19.123px" in css

    pages = _build_pages(document, composed)
    page = pages[0]
    assert "19.123px" in page["content_html"]
    assert page["content_html"].startswith("<style>")

    rendered_ids = _all_ids(_only_component(page["components"]))
    selector_names = _id_selector_names(page["styles"])
    assert selector_names, "expected at least one id-selector style rule"
    assert selector_names <= rendered_ids, (
        "a style selector must target an id that actually exists in the rendered tree"
    )


def _only_component(components: list[dict]) -> dict:
    assert len(components) == 1
    return components[0]


# ---------------------------------------------------------------------------
# Responsive breakpoints: valid @media rules, mobile changes independently.
# ---------------------------------------------------------------------------


def test_desktop_tablet_mobile_declarations_become_valid_media_rules() -> None:
    section = _styled_section(section_id="home.services")
    document = _document(section)
    _, _, composed = _compose(document)
    styles = composed[0]["style_json"]

    base_rule = _rule_for(styles, media=None)
    tablet_rule = _rule_for(styles, media=_TABLET_MEDIA)
    mobile_rule = _rule_for(styles, media=_MOBILE_MEDIA)

    assert base_rule is not None and base_rule["style"]["font-size"] == "720px"
    assert tablet_rule is not None and tablet_rule["style"]["font-size"] == "620px"
    assert tablet_rule["atRuleType"] == "media"
    assert mobile_rule is not None and mobile_rule["style"]["font-size"] == "520px"
    assert mobile_rule["atRuleType"] == "media"

    # Same id anchors every breakpoint's rule -- one section root, one scope.
    ids = {rule["selectors"][0]["name"] for rule in (base_rule, tablet_rule, mobile_rule)}
    assert len(ids) == 1

    # Mobile rule comes last in source order so it wins the cascade against
    # the wider tablet max-width query at narrow viewports.
    assert styles.index(mobile_rule) > styles.index(tablet_rule) > styles.index(base_rule)


def test_mobile_variant_changes_hash_while_desktop_and_tablet_stay_stable() -> None:
    section_a = _styled_section(section_id="home.services", desktop="720px", tablet="620px", mobile="520px")
    section_b = _styled_section(section_id="home.services", desktop="720px", tablet="620px", mobile="560px")

    _, _, composed_a = _compose(_document(section_a))
    _, _, composed_b = _compose(_document(section_b))

    styles_a, styles_b = composed_a[0]["style_json"], composed_b[0]["style_json"]
    assert _rule_for(styles_a, media=None)["style"] == _rule_for(styles_b, media=None)["style"]
    assert (
        _rule_for(styles_a, media=_TABLET_MEDIA)["style"]
        == _rule_for(styles_b, media=_TABLET_MEDIA)["style"]
    )
    assert _rule_for(styles_a, media=_MOBILE_MEDIA)["style"]["font-size"] == "520px"
    assert _rule_for(styles_b, media=_MOBILE_MEDIA)["style"]["font-size"] == "560px"

    assert composed_a[0]["desired_hash"] != composed_b[0]["desired_hash"]

    pages_a = _build_pages(_document(section_a), composed_a)
    pages_b = _build_pages(_document(section_b), composed_b)
    assert pages_a[0]["content_hash"] != pages_b[0]["content_hash"]


def test_recomposing_an_unchanged_plan_is_deterministic() -> None:
    section = _styled_section(section_id="home.services")
    document = _document(section)
    _, library, composed_first = _compose(document)
    composed_second = compose_project_library(copy.deepcopy(library))

    assert composed_first[0]["desired_hash"] == composed_second[0]["desired_hash"]
    assert composed_first[0]["style_json"] == composed_second[0]["style_json"]


# ---------------------------------------------------------------------------
# Scope isolation: two sections' scoped styles never leak onto each other.
# ---------------------------------------------------------------------------


def test_zero_cross_section_style_leakage() -> None:
    section_a = _styled_section(section_id="home.services", desktop="19.123px", tablet="19.123px", mobile="19.123px")
    section_b = _styled_section(section_id="home.more-services", desktop="31.5px", tablet="31.5px", mobile="31.5px")
    section_b = section_b.model_copy(update={"order": 1})
    document = _multi_section_document(section_a, section_b)

    plan, library, composed = _compose(document)
    assert plan.summary.blocking_count == 0
    pages = _build_pages(document, composed)
    page = pages[0]

    ids_a = None
    ids_b = None
    for component in page["components"]:
        section_key = component.get("attributes", {}).get("data-agency-section")
        if section_key == "home.services":
            ids_a = _all_ids(component)
        elif section_key == "home.more-services":
            ids_b = _all_ids(component)
    assert ids_a and ids_b and ids_a.isdisjoint(ids_b)

    for rule in page["styles"]:
        selector_names = {
            selector["name"]
            for selector in rule.get("selectors", [])
            if isinstance(selector, dict) and selector.get("type") == 2
        }
        if not selector_names:
            continue
        # A rule must land entirely within one section's namespaced ids --
        # never straddle both, which would mean one section's accepted
        # style is being applied against the other section's DOM.
        assert selector_names <= ids_a or selector_names <= ids_b

    css = render_styles(page["styles"])
    assert "19.123px" in css
    assert "31.5px" in css


# ---------------------------------------------------------------------------
# Untrusted payload validation: reject before any composition/mutation.
# ---------------------------------------------------------------------------


def _write_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "templates" / "Heroes"
    directory.mkdir(parents=True)
    template = {
        "name": "Test Hero",
        "category": "Heroes",
        "template": {
            "type": "section",
            "attributes": {"id": "section-1"},
            "components": [
                {"type": "heading", "attributes": {"id": "heading-1"}, "content": "Placeholder"}
            ],
        },
        "styles": [],
    }
    (directory / "test-hero.json").write_text(json.dumps(template), encoding="utf-8")
    monkeypatch.setenv("VANJARO_TEMPLATES_DIR", str(tmp_path / "templates"))


def _raw_entry(key: str, **style_fields: object) -> dict:
    entry = {
        "key": key,
        "template": "Test Hero",
        "name": f"project / {key}",
        "category": "Agency - project",
        "type": "custom",
        "overrides": {"heading_1": "Welcome"},
    }
    entry.update(style_fields)
    return entry


_VALID_SCOPE = ".proj-test .design-section-home"


@pytest.mark.parametrize(
    "declarations,scope",
    [
        pytest.param({"font-size": "19px; } .evil{color:red"}, _VALID_SCOPE, id="injection-via-value"),
        pytest.param({"background-image": "url(javascript:alert(1))"}, _VALID_SCOPE, id="javascript-url"),
        pytest.param({"not-a-real-property": "1px"}, _VALID_SCOPE, id="unknown-property"),
        pytest.param({"font-size": "19zz"}, _VALID_SCOPE, id="invalid-unit"),
        pytest.param({"font-size": "19px"}, None, id="missing-scope"),
        pytest.param({"font-size": "19px"}, ".not a valid scope!", id="malformed-scope"),
        pytest.param(
            {
                prop: "1px"
                for prop in (
                    "font-size", "font-weight", "line-height", "letter-spacing", "width",
                    "height", "min-height", "max-width", "margin", "padding", "row-gap",
                    "column-gap", "border-radius",
                )
            },
            _VALID_SCOPE,
            id="budget-exceeded",
        ),
    ],
)
def test_unsafe_or_malformed_style_payload_is_rejected_before_any_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, declarations: dict, scope: str | None
) -> None:
    _write_template(tmp_path, monkeypatch)
    good = _raw_entry("page.section.good")
    bad = _raw_entry("page.section.bad", style_declarations=declarations, style_scope=scope)

    with pytest.raises(BlockLibraryError):
        compose_project_library([good, bad])


def test_legacy_plan_without_style_metadata_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_template(tmp_path, monkeypatch)
    entry = _raw_entry("page.section.legacy")
    assert "style_declarations" not in entry and "style_scope" not in entry

    composed = compose_project_library([entry])

    assert composed[0]["style_json"] == []
    assert composed[0]["content_json"][0]["attributes"]["id"] == "section-1"


# ---------------------------------------------------------------------------
# Asset rewrite: style metadata survives it; URLs inside CSS are not
# silently claimed to be rewritten (they are not -- see notes.md).
# ---------------------------------------------------------------------------


def test_scoped_style_survives_asset_rewrite_pass_without_url_rewriting() -> None:
    section = _feature_section(section_id="home.services").model_copy(
        update={
            "style": StyleSet(
                observations=[
                    StyleObservation(
                        property=StyleProperty.BACKGROUND_IMAGE,
                        value="url(https://source.test/assets/band.jpg)",
                    )
                ]
            )
        }
    )
    document = _document(section)
    plan, library, composed = _compose(document)
    assert "background-image" in plan.entries[0].scoped_css

    asset_records = [
        {
            "vanjaro_url": "https://source.test/assets/band.jpg",
            "variants": [{"width": 800, "url": "https://portal.test/band-800.webp", "format": "webp"}],
        }
    ]
    pages = compose_project_pages(
        document,
        composed,
        {"entries": []},
        project_id="agency-proj",
        isolated=False,
        asset_records=asset_records,
    )
    css = render_styles(pages[0]["styles"])
    # Survives: the declaration is still present after the rewrite pass runs.
    assert "background-image" in css
    # Known gap (see notes.md): rewrite_tree only rewrites attributes.src /
    # attributes.href on components, never a styles[] declaration's value,
    # so the *source* URL is what actually ships, unchanged.
    assert "https://source.test/assets/band.jpg" in css
    assert "portal.test" not in css
