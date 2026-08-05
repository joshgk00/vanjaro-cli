"""Contracts for deriving expected fidelity observations from a Design Document."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vanjaro_cli.design.fidelity_color import ColorRole
from vanjaro_cli.design.fidelity_extraction import (
    MEASURED_METHODS,
    observe_expected_page,
    observe_expected_section,
)
from vanjaro_cli.design.models import (
    AssetKind,
    AssetRecord,
    AssetRole,
    BoundingBox,
    BreakpointName,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    EvidenceStatus,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    ResponsiveObservation,
    Section,
    SourceKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
    Viewport,
)


def _provenance(
    *,
    method: ObservationMethod = ObservationMethod.RENDERED,
    viewport: BreakpointName | None = None,
    bounds: BoundingBox | None = None,
) -> Provenance:
    return Provenance(
        source_kind=SourceKind.LIVE_HTML,
        method=method,
        source_url="https://agency.example/",
        viewport=viewport,
        bounds=bounds,
    )


def _style(*pairs: tuple[StyleProperty, object], status: EvidenceStatus = EvidenceStatus.OBSERVED) -> StyleSet:
    return StyleSet(
        observations=[
            StyleObservation(property=prop, value=value, status=status)
            for prop, value in pairs
        ]
    )


def _element(
    key: str,
    order: int,
    kind: ContentKind,
    *,
    value: str | None = "Copy",
    asset_id: str | None = None,
    style: StyleSet | None = None,
) -> ContentElement:
    return ContentElement(
        id=key,
        order=order,
        kind=kind,
        role="body",
        value=value,
        asset_id=asset_id,
        style=style or StyleSet(),
        provenance=[],
        confidence=1,
    )


def _section(
    *,
    content: list[ContentElement] | None = None,
    style: StyleSet | None = None,
    provenance: list[Provenance] | None = None,
    responsive: list[ResponsiveObservation] | None = None,
    columns: int | None = 3,
) -> Section:
    return Section(
        id="home.section.1",
        order=0,
        semantic_role="feature_cards",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True, columns=columns),
        content=content or [],
        groups=[],
        style=style or StyleSet(),
        responsive=responsive or [],
        decorative_layers=[],
        interactions=[],
        provenance=provenance or [],
    )


def _observe(section: Section, breakpoint: BreakpointName = BreakpointName.DESKTOP, assets=None):
    return observe_expected_section(section, assets or {}, breakpoint)


def test_measured_geometry_is_read_from_provenance_bounds() -> None:
    box = BoundingBox(x=0, y=120, width=1440, height=560)
    observation = _observe(
        _section(provenance=[_provenance(viewport=BreakpointName.DESKTOP, bounds=box)])
    )

    assert observation.geometry.bounds is not None
    assert observation.geometry.bounds.height == 560


def test_inferred_geometry_is_dropped_rather_than_scored_as_measured() -> None:
    # SectionGeometry cannot carry the observation method, so an inferred box
    # would be indistinguishable from a measurement against 0.60 of layout.
    box = BoundingBox(x=0, y=0, width=1440, height=400)
    observation = _observe(
        _section(
            provenance=[
                _provenance(
                    method=ObservationMethod.INFERRED,
                    viewport=BreakpointName.DESKTOP,
                    bounds=box,
                )
            ]
        )
    )

    assert observation.geometry.bounds is None
    assert ObservationMethod.INFERRED not in MEASURED_METHODS


def test_geometry_from_another_viewport_is_never_reused() -> None:
    box = BoundingBox(x=0, y=0, width=1440, height=400)
    section = _section(
        provenance=[_provenance(viewport=BreakpointName.DESKTOP, bounds=box)]
    )

    assert _observe(section, BreakpointName.MOBILE).geometry.bounds is None


def test_viewportless_measurement_describes_the_desktop_base_layout() -> None:
    box = BoundingBox(x=0, y=0, width=1440, height=400)
    section = _section(provenance=[_provenance(bounds=box)])

    assert _observe(section, BreakpointName.DESKTOP).geometry.bounds is not None
    assert _observe(section, BreakpointName.TABLET).geometry.bounds is None


def test_responsive_column_change_overrides_the_base_layout() -> None:
    section = _section(
        columns=3,
        responsive=[
            ResponsiveObservation(
                breakpoint=BreakpointName.MOBILE,
                viewport=Viewport(width=390, height=844),
                status=EvidenceStatus.OBSERVED,
                layout_changes={"columns": 1},
            )
        ],
    )

    assert _observe(section, BreakpointName.DESKTOP).geometry.columns == 3
    assert _observe(section, BreakpointName.MOBILE).geometry.columns == 1


def test_palette_reads_section_colours_and_an_action_accent() -> None:
    action = _element(
        "cta",
        2,
        ContentKind.BUTTON,
        style=_style((StyleProperty.BACKGROUND_COLOR, "#ff5500")),
    )
    section = _section(
        content=[action],
        style=_style(
            (StyleProperty.BACKGROUND_COLOR, "#ffffff"),
            (StyleProperty.TEXT_COLOR, "#111111"),
        ),
    )

    palette = _observe(section).palette

    assert palette.get(ColorRole.BACKGROUND) == "#ffffff"
    assert palette.get(ColorRole.TEXT) == "#111111"
    assert palette.get(ColorRole.ACCENT) == "#ff5500"


def test_inferred_style_values_are_not_treated_as_observed_evidence() -> None:
    section = _section(
        style=_style((StyleProperty.BACKGROUND_COLOR, "#ffffff"), status=EvidenceStatus.INFERRED)
    )

    assert _observe(section).palette.get(ColorRole.BACKGROUND) is None


def test_typography_samples_come_from_the_first_heading_and_body() -> None:
    heading = _element(
        "h",
        1,
        ContentKind.HEADING,
        style=_style(
            (StyleProperty.FONT_FAMILY, "Inter"),
            (StyleProperty.FONT_SIZE, "48px"),
            (StyleProperty.FONT_WEIGHT, 700),
        ),
    )
    body = _element(
        "p", 2, ContentKind.TEXT, style=_style((StyleProperty.FONT_SIZE, 16))
    )

    typography = _observe(_section(content=[heading, body])).typography

    assert typography.samples["heading"].family == "Inter"
    assert typography.samples["heading"].size_px == 48
    assert typography.samples["heading"].weight == 700
    assert typography.samples["body"].size_px == 16
    assert typography.samples["body"].family is None


def test_a_section_without_type_evidence_reports_no_samples() -> None:
    assert _observe(_section(content=[_element("p", 1, ContentKind.TEXT)])).typography.samples == {}


@pytest.mark.parametrize(
    ("declared", "expected_top", "expected_bottom"),
    [
        (64, 64.0, 64.0),
        ("48px", 48.0, 48.0),
        ("40px 0", 40.0, 40.0),
        ("40px 0 24px", 40.0, 24.0),
        ("40px 0 24px 0", 40.0, 24.0),
        ("0", 0.0, 0.0),
    ],
)
def test_padding_shorthand_is_read_without_guessing(
    declared: object, expected_top: float, expected_bottom: float
) -> None:
    spacing = _observe(_section(style=_style((StyleProperty.PADDING, declared)))).spacing.spacing

    assert spacing.padding_top == expected_top
    assert spacing.padding_bottom == expected_bottom


def test_measured_zero_padding_is_evidence_not_absence() -> None:
    # A section with its padding stripped must score as a mismatch, not drop
    # out of the spacing dimension entirely.
    spacing = _observe(_section(style=_style((StyleProperty.PADDING, 0)))).spacing.spacing

    assert spacing.padding_top == 0.0


def test_unreadable_padding_is_unavailable_rather_than_a_guess() -> None:
    spacing = _observe(
        _section(style=_style((StyleProperty.PADDING, "clamp(1rem, 4vw, 5rem)")))
    ).spacing.spacing

    assert spacing.padding_top is None
    assert spacing.padding_bottom is None


def test_media_aspect_comes_from_asset_intrinsics_and_placement_stays_unavailable() -> None:
    asset = AssetRecord(
        id="asset-1",
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        source_url="https://agency.example/one.jpg",
        width=1600,
        height=900,
    )
    section = _section(content=[_element("img", 1, ContentKind.IMAGE, asset_id="asset-1")])

    sample = _observe(section, assets={"asset-1": asset}).media.media["media_1"]

    assert sample.aspect_ratio == pytest.approx(16 / 9)
    # Focal point and crop describe how a build placed the image; a design
    # cannot supply either side of that comparison.
    assert sample.focal_x is None
    assert sample.crop_coverage is None


def test_asset_without_intrinsic_size_yields_no_media_sample() -> None:
    asset = AssetRecord(
        id="asset-1",
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        source_url="https://agency.example/one.jpg",
    )
    section = _section(content=[_element("img", 1, ContentKind.IMAGE, asset_id="asset-1")])

    assert _observe(section, assets={"asset-1": asset}).media.media == {}


def test_integrity_has_no_expected_side() -> None:
    assert _observe(_section()).integrity is None


def _document(page: Page, assets: list[AssetRecord] | None = None) -> DesignDocument:
    return DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://agency.example/",
            captured_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            adapter_version="1.0.0",
        ),
        tokens=DesignTokens(),
        assets=assets or [],
        pages=[page],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )


def _page(sections: list[Section]) -> Page:
    return Page(
        id="home",
        source_reference="https://agency.example/",
        title="Home",
        slug="home",
        sections=sections,
        breakpoints=[BreakpointName.DESKTOP],
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=[],
    )


def test_page_observation_uses_the_canonical_viewport_and_section_order() -> None:
    first = _section()
    second = _section().model_copy(update={"id": "home.section.2", "order": 1})
    page = _page([second, first])

    observation = observe_expected_page(page, _document(page), BreakpointName.MOBILE)

    assert observation is not None
    assert observation.viewport_width == 390
    assert [item.section_id for item in observation.sections] == [
        "home.section.1",
        "home.section.2",
    ]


def test_a_page_without_sections_produces_no_observation() -> None:
    page = _page([])

    assert observe_expected_page(page, _document(page), BreakpointName.DESKTOP) is None


def test_extraction_is_deterministic() -> None:
    page = _page([_section()])
    document = _document(page)

    first = observe_expected_page(page, document, BreakpointName.DESKTOP)
    second = observe_expected_page(page, document, BreakpointName.DESKTOP)

    assert first is not None and second is not None
    assert first.model_dump_json() == second.model_dump_json()
