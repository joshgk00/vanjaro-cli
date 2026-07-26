"""Source-neutral responsive composition and ambiguity coverage."""

from __future__ import annotations

from datetime import UTC, datetime

from vanjaro_cli.design.composite import CompositeDesignInput, merge_design_documents
from vanjaro_cli.design.models import (
    BreakpointName,
    DesignWarning,
    EvidenceStatus,
    LayoutKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
)
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import HtmlSourceRequest, analyze_source


CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)
HTML = """<html><body><main><section><h1>Responsive evidence</h1></section></main></body></html>"""


def _document(
    source_id: str,
    breakpoint: BreakpointName,
    *,
    columns: int,
    color: str,
):
    document = analyze_source(
        HtmlSourceRequest(
            html=HTML,
            source_url=f"https://{source_id}.example/",
            captured_at=CAPTURED_AT,
        )
    )
    page = document.pages[0]
    section = page.sections[0]
    section = section.model_copy(
        update={
            "layout": section.layout.model_copy(
                update={"kind": LayoutKind.GRID, "columns": columns}
            ),
            "style": StyleSet(
                observations=[
                    StyleObservation(
                        property=StyleProperty.BACKGROUND_COLOR,
                        value=color,
                    )
                ]
            ),
            "responsive": [],
        }
    )
    page = page.model_copy(
        update={
            "sections": [section],
            "breakpoints": [breakpoint],
            "metadata": {"source_breakpoint": breakpoint.value},
        }
    )
    return document.model_copy(update={"pages": [page]})


def _input(source_id: str, document) -> CompositeDesignInput:
    return CompositeDesignInput(
        source_id=source_id,
        page_reference="home",
        document=document,
    )


def test_desktop_is_canonical_and_merge_is_input_order_independent() -> None:
    mobile = _document(
        "mobile", BreakpointName.MOBILE, columns=1, color="#222222"
    )
    mobile = mobile.model_copy(
        update={
            "warnings": [
                DesignWarning(
                    code="mobile_source_warning",
                    message="Mobile evidence needs editorial review.",
                )
            ]
        }
    )
    desktop = _document(
        "desktop", BreakpointName.DESKTOP, columns=3, color="#ffffff"
    )
    # The mobile source sorts first by ID, so breakpoint priority—not source
    # ordering—must choose the desktop page.
    first = merge_design_documents(
        "responsive",
        [_input("image-1-mobile", mobile), _input("image-2-desktop", desktop)],
    )
    second = merge_design_documents(
        "responsive",
        [_input("image-2-desktop", desktop), _input("image-1-mobile", mobile)],
    )

    assert serialize_design_document(first) == serialize_design_document(second)
    page = first.pages[0]
    section = page.sections[0]
    assert page.metadata["canonical_project_source"] == "image-2-desktop"
    assert page.metadata["canonical_breakpoint"] == "desktop"
    assert section.layout.columns == 3
    assert page.breakpoints == [BreakpointName.DESKTOP, BreakpointName.MOBILE]
    mobile_evidence = next(
        item for item in section.responsive
        if item.breakpoint == BreakpointName.MOBILE
    )
    assert mobile_evidence.status == EvidenceStatus.OBSERVED
    assert mobile_evidence.layout_changes["columns"] == {"from": 3, "to": 1}
    assert mobile_evidence.style.observations[0].value == "#222222"
    assert len(section.provenance) >= 2
    assert any(warning.code == "mobile_source_warning" for warning in first.warnings)


def test_ambiguous_section_pairing_retains_secondary_section_and_warns() -> None:
    desktop = _document(
        "desktop", BreakpointName.DESKTOP, columns=3, color="#ffffff"
    )
    base = desktop.pages[0].sections[0]
    first = _clone_section(base, "desktop-feature-a", 0)
    second = _clone_section(base, "desktop-feature-b", 1)
    desktop = desktop.model_copy(
        update={
            "pages": [desktop.pages[0].model_copy(update={"sections": [first, second]})]
        }
    )
    mobile = _document(
        "mobile", BreakpointName.MOBILE, columns=1, color="#222222"
    )
    ambiguous = _clone_section(mobile.pages[0].sections[0], "mobile-feature", 4)
    mobile = mobile.model_copy(
        update={
            "pages": [mobile.pages[0].model_copy(update={"sections": [ambiguous]})]
        }
    )

    combined = merge_design_documents(
        "ambiguous", [_input("desktop", desktop), _input("mobile", mobile)]
    )

    assert len(combined.pages[0].sections) == 3
    retained = combined.pages[0].sections[-1]
    assert retained.metadata["responsive_pairing_status"] == "ambiguous"
    assert retained.content[0].value == "Responsive evidence"
    assert any(
        warning.code == "ambiguous_paired_section"
        for warning in combined.warnings
    )


def test_matched_content_divergence_is_explicit_and_canonical_copy_remains() -> None:
    desktop = _document(
        "desktop", BreakpointName.DESKTOP, columns=3, color="#ffffff"
    )
    mobile = _document(
        "mobile", BreakpointName.MOBILE, columns=1, color="#222222"
    )
    mobile_page = mobile.pages[0]
    mobile_section = mobile_page.sections[0]
    mobile_content = mobile_section.content[0].model_copy(
        update={"value": "Different mobile copy"}
    )
    mobile_section = mobile_section.model_copy(update={"content": [mobile_content]})
    mobile = mobile.model_copy(
        update={
            "pages": [mobile_page.model_copy(update={"sections": [mobile_section]})]
        }
    )

    combined = merge_design_documents(
        "divergent", [_input("desktop", desktop), _input("mobile", mobile)]
    )

    section = combined.pages[0].sections[0]
    assert section.content[0].value == "Responsive evidence"
    differences = section.metadata["paired_evidence_differences"]
    assert differences[0]["source_id"] == "mobile"
    assert differences[0]["unmatched_secondary_content_ids"]
    assert any(
        warning.code == "paired_section_structure_divergence"
        for warning in combined.warnings
    )


def test_single_source_still_returns_byte_equivalent_document() -> None:
    document = _document(
        "single", BreakpointName.DESKTOP, columns=3, color="#ffffff"
    )
    merged = merge_design_documents(
        "single", [_input("only-source", document)]
    )
    assert serialize_design_document(merged) == serialize_design_document(document)


def _clone_section(section, identifier: str, order: int):
    content = [
        element.model_copy(update={"id": f"{identifier}-content-{index}"})
        for index, element in enumerate(section.content)
    ]
    return section.model_copy(
        update={
            "id": identifier,
            "order": order,
            "semantic_role": "feature_cards",
            "content": content,
        }
    )
