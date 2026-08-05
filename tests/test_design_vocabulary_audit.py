"""Standing guard that observed roles can reach declared template fields."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from vanjaro_cli.design.models import (
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    Page,
    RepeatGroup,
    RepeatGroupItem,
    RepeatGroupKind,
    Section,
    SourceKind,
    StyleSet,
)
from vanjaro_cli.design.sources import (
    FigmaSourceRequest,
    HtmlSourceRequest,
    analyze_source,
)
from vanjaro_cli.design.template_catalog import load_template_catalog
from vanjaro_cli.design.vocabulary_audit import (
    audit_vocabulary,
    declared_fields,
    observed_vocabulary,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "design-benchmarks"
CAPTURED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _corpus_documents() -> list[DesignDocument]:
    """Run the real adapters over every corpus fixture they support."""

    manifest = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))
    documents: list[DesignDocument] = []
    for case in manifest["cases"]:
        path = CORPUS_ROOT / case["source"]["path"]
        if case["source_kind"] == "live_html":
            request = HtmlSourceRequest(
                html=path.read_text(encoding="utf-8"),
                source_url=f"https://benchmark.invalid/{case['id']}",
                title=case.get("title"),
                captured_at=CAPTURED_AT,
            )
        elif case["source_kind"] == "figma":
            request = FigmaSourceRequest(
                payload=json.loads(path.read_text(encoding="utf-8")),
                file_key=case["id"],
                captured_at=CAPTURED_AT,
            )
        else:
            # Image cases need acquired reference files; the html and figma
            # adapters already exercise the shared vocabulary.
            continue
        documents.append(analyze_source(request))
    return documents


@pytest.fixture(scope="module")
def corpus_audit():
    return audit_vocabulary(_corpus_documents(), load_template_catalog())


def test_no_observed_role_is_unable_to_reach_a_template_field(corpus_audit) -> None:
    # A role no field accepts is content the pipeline can see but never place.
    # Matching still scores it, so nothing else catches this.
    assert corpus_audit.unreachable_section_roles == ()
    assert corpus_audit.unreachable_item_fields == ()


def test_unsatisfiable_required_fields_are_limited_to_unexercised_templates(
    corpus_audit,
) -> None:
    """Required fields nothing can satisfy, because the corpus lacks the content.

    These are a corpus coverage gap, not a vocabulary defect: no fixture
    contains an FAQ, a price, or a multi-column footer. Inventing aliases to
    clear this list would map real content onto fields it does not belong in.
    If a fixture later grows that content, the entry must disappear from here
    rather than be added below.
    """

    assert set(corpus_audit.unsatisfiable_required_fields) == {
        ("Cards/pricing-cards-3up", "item.price"),
        ("Content/faq-accordion", "item.answer"),
        ("Content/faq-accordion", "item.question"),
        ("Navigation/footer-3col", "column.links"),
        ("Navigation/footer-3col", "column.title"),
        ("Navigation/footer-3col", "contact_title"),
        ("Navigation/footer-4col", "column.links"),
        ("Navigation/footer-4col", "column.title"),
        ("Navigation/footer-4col", "contact_title"),
    }


def _document(section: Section) -> DesignDocument:
    page = Page(
        id="home",
        source_reference="https://agency.example/",
        title="Home",
        slug="home",
        sections=[section],
        breakpoints=[],
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=[],
    )
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://agency.example/",
            captured_at=CAPTURED_AT,
            adapter_version="1.0.0",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[page],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def _section(content: list[ContentElement], groups: list[RepeatGroup]) -> Section:
    return Section(
        id="home.s1",
        order=0,
        semantic_role="feature_cards",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True),
        content=content,
        groups=groups,
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[],
    )


def _element(key: str, role: str, group_id: str | None = None) -> ContentElement:
    return ContentElement(
        id=key,
        order=1,
        kind=ContentKind.TEXT,
        role=role,
        value="Copy",
        group_id=group_id,
        provenance=[],
        confidence=1,
    )


def test_a_role_no_template_accepts_is_reported() -> None:
    document = _document(_section([_element("x", "sponsorship_tier")], []))

    audit = audit_vocabulary([document], load_template_catalog())

    assert "sponsorship_tier" in audit.unreachable_section_roles
    assert audit.clean is False


def test_grouped_elements_are_audited_as_item_roles_not_section_roles() -> None:
    group = RepeatGroup(
        id="g1",
        kind=RepeatGroupKind.CARD,
        items=[RepeatGroupItem(id="i1", fields={"title": "x"})],
        provenance=[],
    )
    document = _document(_section([_element("x", "card_title", group_id="g1")], [group]))

    vocabulary = observed_vocabulary([document])

    assert vocabulary.item_roles == ("card_title",)
    assert vocabulary.section_roles == ()
    assert vocabulary.item_fields == ("title",)


def test_declared_fields_include_static_as_well_as_editable_fields() -> None:
    catalog = load_template_catalog()

    declared = declared_fields(catalog)

    assert "section_title" in declared
    assert declared.issuperset(
        {field for entry in catalog for field in entry.capabilities.fields}
    )


def test_an_empty_corpus_reports_nothing_rather_than_everything() -> None:
    # No observations means no evidence of a gap, not proof of one.
    audit = audit_vocabulary([], load_template_catalog())

    assert audit.unreachable_section_roles == ()
    assert audit.unreachable_item_fields == ()
