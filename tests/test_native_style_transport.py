"""Native (class-based) style decision transport: planner -> emitter -> compose -> page.

The scoped-CSS transport (``style_transport.py``) already had maintained
coverage. Nothing exercised the other translation layers reaching a real
composed component: an accepted platform-utility, theme, or agency-utility
decision was computed by ``style_translation.py`` and then discarded before
``compose_project_library`` ever saw it. These tests exercise the real
``plan_design_document`` -> ``emit_library_plan`` -> ``compose_project_library``
-> (for the alignment case) ``compose_project_pages`` path, asserting on the
actual generated DOM classes and content, not just new report fields.
"""

from __future__ import annotations

from pathlib import Path
import runpy

import pytest
from bs4 import BeautifulSoup

from vanjaro_cli.design.models import (
    BreakpointName,
    EvidenceStatus,
    ResponsiveObservation,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)
from vanjaro_cli.design.native_style_transport import (
    NativeStyleTransportError,
    apply_native_class_actions,
    build_native_style_report,
    validate_native_class_actions,
)
from vanjaro_cli.design.planner import PlanningError, emit_library_plan, plan_design_document
from vanjaro_cli.design.style_translation import (
    DEFAULT_AVAILABLE_PLATFORM_UTILITIES,
    StyleTranslationConfig,
)
from vanjaro_cli.portal.block_library import BlockLibraryError, compose_project_library
from vanjaro_cli.portal.page_composition import compose_project_pages
from vanjaro_cli.utils.grapesjs import render_components


_FIXTURE = runpy.run_path(
    str(Path(__file__).resolve().parent / "test_design_planner.py")
)
_feature_section = _FIXTURE["_feature_section"]
_document = _FIXTURE["_document"]
CATALOG = _FIXTURE["CATALOG"]


def _section_root_classes(block: dict) -> set[str]:
    component = block["content_json"][0]
    return {
        entry["name"]
        for entry in component.get("classes", [])
        if isinstance(entry, dict) and "name" in entry
    }


def _rendered_text(block: dict) -> str:
    soup = BeautifulSoup(render_components(block["content_json"]), "html.parser")
    return soup.get_text(" ", strip=True)


# --- alignment: real planner -> emitter -> compose -> page -----------------


def test_text_align_reaches_the_composed_section_and_the_composed_page():
    section = _feature_section().model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right")])}
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    entry = plan.entries[0]
    decision = next(item for item in entry.style_decisions if item.property == StyleProperty.TEXT_ALIGN)
    assert decision.target == "text-end"
    assert decision.layer.value == "platform_utility"

    library = emit_library_plan(plan)
    assert library[0]["native_classes"] == [
        {
            "property": "text_align",
            "source_value": "right",
            "layer": "platform_utility",
            "target": "text-end",
            "family": ["text-center", "text-end", "text-start"],
            "breakpoint": None,
        }
    ]

    blocks = compose_project_library(library)
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    assert "text-end" in _section_root_classes(block)
    assert "Our Services" in _rendered_text(block)

    page = compose_project_pages(
        document, blocks, {"entries": []}, project_id="native-style-proof", isolated=True
    )[0]
    soup = BeautifulSoup(page["content_html"], "html.parser")
    targets = soup.select(".text-end")
    assert any("Our Services" in node.get_text(" ", strip=True) for node in targets)


# --- theme colors: safe slot reused as bg-*/text-*, unsafe slot reported ----


def test_safe_theme_slot_is_reused_as_a_class():
    section = _feature_section().model_copy(
        update={
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#112233")]
            )
        }
    )
    document = _document(section)
    config = StyleTranslationConfig(palette={"primary": "#112233"})
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    entry = plan.entries[0]
    decision = next(item for item in entry.style_decisions if item.property == StyleProperty.BACKGROUND_COLOR)
    assert decision.layer.value == "theme"
    assert decision.target == "bg-primary"
    assert not any("bg-primary" in warning or "background_color" in warning for warning in entry.warnings)

    library = emit_library_plan(plan)
    blocks = compose_project_library(library)
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    assert "bg-primary" in _section_root_classes(block)


def test_extended_palette_slot_is_reported_not_guessed_as_a_class():
    """`tertiary`/`quaternary` are Vanjaro palette slots with no Bootstrap 5.1
    bg-*/text-* utility class -- the target is a token identifier, and a
    dropped decision here must never be counted as applied."""

    section = _feature_section().model_copy(
        update={
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#556677")]
            )
        }
    )
    document = _document(section)
    config = StyleTranslationConfig(palette={"tertiary": "#556677"})
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    entry = plan.entries[0]
    decision = next(item for item in entry.style_decisions if item.property == StyleProperty.BACKGROUND_COLOR)
    assert decision.target == "bg-tertiary"
    assert any("token/variable identifier" in warning for warning in entry.warnings)

    library = emit_library_plan(plan)
    assert "native_classes" not in library[0]
    blocks = compose_project_library(library)
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    assert "bg-tertiary" not in _section_root_classes(block)


# --- class conflicts: a later decision replaces an earlier one, never both -


def test_conflicting_decisions_for_one_property_leave_only_the_final_class():
    section = _feature_section().model_copy(
        update={
            "style": StyleSet(
                observations=[
                    StyleObservation(property=StyleProperty.TEXT_ALIGN, value="left"),
                    StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right"),
                ]
            )
        }
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    entry = plan.entries[0]
    assert any("superseded" in warning for warning in entry.warnings)

    blocks = compose_project_library(emit_library_plan(plan))
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    classes = _section_root_classes(block)
    assert "text-end" in classes
    assert "text-start" not in classes


def test_build_native_style_report_is_empty_for_no_decisions():
    report = build_native_style_report([])
    assert report.actions == ()
    assert report.diagnostics == ()


def test_apply_native_class_actions_removes_a_templates_own_baked_in_family_member():
    from vanjaro_cli.design.native_style_transport import NativeClassAction

    action = NativeClassAction(
        property=StyleProperty.TEXT_ALIGN,
        source_value="right",
        layer="platform_utility",
        target="text-end",
        family=("text-start", "text-center", "text-end"),
    )
    component = {
        "type": "section",
        "classes": [{"name": "vj-section", "active": False}, {"name": "text-start", "active": False}],
    }
    apply_native_class_actions(component, (action,))
    names = [entry["name"] for entry in component["classes"]]
    assert names == ["vj-section", "text-end"]


# --- two independent sections: no cross-contamination, distinct hashes -----


def test_two_sections_apply_only_their_own_native_classes():
    aligned = _feature_section(
        section_id="home.services", element_prefix="a-element", group_id="a-cards", item_prefix="a-card"
    ).model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right")])}
    )
    themed = _feature_section(
        section_id="home.more-services", element_prefix="b-element", group_id="b-cards", item_prefix="b-card"
    ).model_copy(
        update={
            "order": 1,
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#112233")]
            ),
        }
    )
    document = _document(aligned)
    document = document.model_copy(
        update={"pages": [document.pages[0].model_copy(update={"sections": [aligned, themed]})]}
    )
    config = StyleTranslationConfig(palette={"primary": "#112233"})
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    blocks = compose_project_library(emit_library_plan(plan))
    by_key = {block["key"]: block for block in blocks}

    assert _section_root_classes(by_key["home.services"]) & {"text-end"}
    assert not _section_root_classes(by_key["home.services"]) & {"bg-primary"}
    assert _section_root_classes(by_key["home.more-services"]) & {"bg-primary"}
    assert not _section_root_classes(by_key["home.more-services"]) & {"text-end"}
    assert by_key["home.services"]["desired_hash"] != by_key["home.more-services"]["desired_hash"]


# --- safe agency mapping -----------------------------------------------


def test_declared_agency_utility_mapping_is_transported():
    agency_utilities = {"order:2": "order-2", "order:1": "order-1"}
    section = _feature_section().model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.ORDER, value="2")])}
    )
    document = _document(section)
    config = StyleTranslationConfig(agency_utilities=agency_utilities)
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    entry = plan.entries[0]
    decision = next(item for item in entry.style_decisions if item.property == StyleProperty.ORDER)
    assert decision.layer.value == "agency_utility"
    assert decision.target == "order-2"

    library = emit_library_plan(plan, agency_utilities=agency_utilities)
    assert library[0]["native_classes"][0]["target"] == "order-2"
    blocks = compose_project_library(library, agency_utilities=agency_utilities)
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    assert "order-2" in _section_root_classes(block)


def test_agency_utility_without_a_declared_mapping_at_compose_time_is_rejected():
    """The mapping must be declared explicitly at *each* boundary that trusts it --
    a payload claiming an agency-utility class is never trusted just because it
    parsed, since compose_project_library has no other way to confirm it is a
    real, deliberately configured class."""

    agency_utilities = {"order:2": "order-2"}
    section = _feature_section().model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.ORDER, value="2")])}
    )
    document = _document(section)
    config = StyleTranslationConfig(agency_utilities=agency_utilities)
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    library = emit_library_plan(plan, agency_utilities=agency_utilities)

    with pytest.raises(BlockLibraryError):
        compose_project_library(library)  # no agency_utilities supplied here


# --- unsupported modifier / target handling --------------------------------


def test_unsupported_template_modifier_is_reported_and_not_applied():
    section = _feature_section().model_copy(
        update={
            "style": StyleSet(
                observations=[StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#abcdef")]
            )
        }
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)  # default config: empty palette
    entry = plan.entries[0]
    decision = next(item for item in entry.style_decisions if item.property == StyleProperty.BACKGROUND_COLOR)
    assert decision.layer.value == "template_modifier"
    assert any("capability label" in warning for warning in entry.warnings)

    library = emit_library_plan(plan)
    assert "native_classes" not in library[0]


# --- unsafe serialized action fields ---------------------------------------


def test_validate_rejects_a_target_not_in_the_recomputed_true_family():
    raw = [
        {
            "property": "text_align",
            "source_value": "right",
            "layer": "platform_utility",
            "target": "d-flex",
            "family": ["d-flex"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions(raw)


def test_validate_rejects_a_breakpoint_scoped_action():
    raw = [
        {
            "property": "text_align",
            "source_value": "right",
            "layer": "platform_utility",
            "target": "text-end",
            "family": ["text-start", "text-center", "text-end"],
            "breakpoint": "tablet",
        }
    ]
    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions(raw)


def test_validate_rejects_agency_utility_target_with_no_declared_mapping():
    raw = [
        {
            "property": "order",
            "source_value": "2",
            "layer": "agency_utility",
            "target": "order-2",
            "family": ["order-2"],
            "breakpoint": None,
        }
    ]
    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions(raw)
    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions(raw, agency_utilities={"order:9": "order-9"})


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-list",
        [{"property": "text_align"}],
        [
            {
                "property": "text_align",
                "source_value": "right",
                "layer": "scoped_css",
                "target": "text-end",
                "family": ["text-end"],
                "breakpoint": None,
            }
        ],
        [
            {
                "property": "text_align",
                "source_value": "right",
                "layer": "platform_utility",
                "target": "text-end<script>",
                "family": ["text-end<script>"],
                "breakpoint": None,
            }
        ],
    ],
)
def test_validate_rejects_malformed_or_unsafe_payload_shapes(raw):
    with pytest.raises(NativeStyleTransportError):
        validate_native_class_actions(raw)


def test_compose_project_library_rejects_untrusted_native_classes_entry():
    section = _feature_section().model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right")])}
    )
    plan = plan_design_document(_document(section), catalog=CATALOG)
    library = emit_library_plan(plan)
    library[0]["native_classes"][0]["target"] = "d-flex"
    with pytest.raises(BlockLibraryError):
        compose_project_library(library)


# --- media owner ambiguity ---------------------------------------------


def test_media_only_property_is_never_applied_to_the_section_root():
    """Even when the utility class itself would be considered available, an
    OBJECT_FIT/OBJECT_POSITION decision observed at section scope has no
    single owning image component -- applying it to the section div would be
    exactly the failure this transport exists to prevent."""

    section = _feature_section().model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.OBJECT_FIT, value="cover")])}
    )
    document = _document(section)
    config = StyleTranslationConfig(
        available_platform_utilities=DEFAULT_AVAILABLE_PLATFORM_UTILITIES | {"object-fit-cover"}
    )
    plan = plan_design_document(document, catalog=CATALOG, style_config=config)
    entry = plan.entries[0]
    decision = next(item for item in entry.style_decisions if item.property == StyleProperty.OBJECT_FIT)
    assert decision.layer.value == "platform_utility"
    assert decision.target == "object-fit-cover"
    assert any("no unique image/media owner" in warning for warning in entry.warnings)

    library = emit_library_plan(plan)
    assert "native_classes" not in library[0]
    blocks = compose_project_library(library)
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    assert "object-fit-cover" not in _section_root_classes(block)


# --- responsive ambiguity ------------------------------------------------


def test_responsive_native_decision_is_reported_not_guessed():
    """A breakpoint-scoped native decision must never be applied unconditionally
    (that would silently contradict the desktop decision) and no Bootstrap
    responsive variant is assumed to exist for every utility."""

    section = _feature_section().model_copy(
        update={
            "style": StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="left")]),
            "responsive": [
                ResponsiveObservation(
                    breakpoint=BreakpointName.TABLET,
                    viewport=Viewport(width=768, height=1024),
                    status=EvidenceStatus.OBSERVED,
                    style=StyleSet(
                        observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right")]
                    ),
                    provenance=[],
                )
            ],
        }
    )
    document = _document(section)
    plan = plan_design_document(document, catalog=CATALOG)
    entry = plan.entries[0]
    assert any(
        "responsive (tablet)" in warning and "not applied" in warning for warning in entry.warnings
    )

    blocks = compose_project_library(emit_library_plan(plan))
    block = next(item for item in blocks if item["key"] == entry.source_section_id)
    classes = _section_root_classes(block)
    assert "text-start" in classes
    assert "text-end" not in classes


# --- hash changes and unchanged repeats -------------------------------------


def test_native_class_changes_desired_hash_and_repeat_builds_are_identical():
    baseline_section = _feature_section()
    styled_section = baseline_section.model_copy(
        update={"style": StyleSet(observations=[StyleObservation(property=StyleProperty.TEXT_ALIGN, value="right")])}
    )

    baseline_plan = plan_design_document(_document(baseline_section), catalog=CATALOG)
    styled_plan = plan_design_document(_document(styled_section), catalog=CATALOG)
    baseline_blocks = compose_project_library(emit_library_plan(baseline_plan))
    styled_blocks = compose_project_library(emit_library_plan(styled_plan))

    assert baseline_blocks[0]["desired_hash"] != styled_blocks[0]["desired_hash"]
    assert "text-end" not in _section_root_classes(baseline_blocks[0])

    repeat_plan = plan_design_document(_document(styled_section), catalog=CATALOG)
    repeat_blocks = compose_project_library(emit_library_plan(repeat_plan))
    assert repeat_blocks == styled_blocks
    assert repeat_blocks[0]["desired_hash"] == styled_blocks[0]["desired_hash"]
