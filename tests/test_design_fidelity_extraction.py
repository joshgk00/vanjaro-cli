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


def _responsive_with_bounds(
    breakpoint: BreakpointName,
    box: BoundingBox,
    *,
    method: ObservationMethod = ObservationMethod.RENDERED,
) -> ResponsiveObservation:
    return ResponsiveObservation(
        breakpoint=breakpoint,
        viewport=Viewport(width=int(box.width), height=800),
        status=EvidenceStatus.OBSERVED,
        provenance=[_provenance(method=method, viewport=breakpoint, bounds=box)],
    )


def test_non_desktop_geometry_is_read_from_the_responsive_observation() -> None:
    """A rendered crawl measures every breakpoint and records the non-desktop
    boxes on the responsive observation, because the section's own provenance
    describes its base layout. Reading only the section left tablet and mobile
    with no geometry, so layout scored on columns and order alone."""

    desktop_box = BoundingBox(x=8, y=196, width=1424, height=365)
    tablet_box = BoundingBox(x=8, y=196, width=752, height=420)
    section = _section(
        provenance=[_provenance(viewport=BreakpointName.DESKTOP, bounds=desktop_box)],
        responsive=[_responsive_with_bounds(BreakpointName.TABLET, tablet_box)],
    )

    assert _observe(section, BreakpointName.DESKTOP).geometry.bounds.width == 1424
    assert _observe(section, BreakpointName.TABLET).geometry.bounds.width == 752
    assert _observe(section, BreakpointName.MOBILE).geometry.bounds is None


def test_a_responsive_box_is_never_borrowed_for_another_breakpoint() -> None:
    section = _section(
        provenance=[],
        responsive=[
            _responsive_with_bounds(
                BreakpointName.TABLET, BoundingBox(x=0, y=0, width=752, height=400)
            )
        ],
    )

    assert _observe(section, BreakpointName.TABLET).geometry.bounds is not None
    assert _observe(section, BreakpointName.MOBILE).geometry.bounds is None
    assert _observe(section, BreakpointName.DESKTOP).geometry.bounds is None


def test_an_inferred_responsive_box_is_still_refused() -> None:
    """Provenance decides what counts, and the responsive path is no exception."""

    section = _section(
        provenance=[],
        responsive=[
            _responsive_with_bounds(
                BreakpointName.MOBILE,
                BoundingBox(x=0, y=0, width=374, height=500),
                method=ObservationMethod.INFERRED,
            )
        ],
    )

    assert _observe(section, BreakpointName.MOBILE).geometry.bounds is None


def test_the_section_provenance_still_wins_when_it_names_the_breakpoint() -> None:
    exact = BoundingBox(x=0, y=0, width=390, height=700)
    section = _section(
        provenance=[_provenance(viewport=BreakpointName.MOBILE, bounds=exact)],
        responsive=[
            _responsive_with_bounds(
                BreakpointName.MOBILE, BoundingBox(x=9, y=9, width=374, height=500)
            )
        ],
    )

    assert _observe(section, BreakpointName.MOBILE).geometry.bounds.width == 390


def _named_style(**values: str) -> StyleSet:
    return StyleSet(
        observations=[
            StyleObservation(property=StyleProperty(name), value=value)
            for name, value in values.items()
        ]
    )


def _responsive_style(
    breakpoint: BreakpointName,
    style: StyleSet,
    *,
    method: ObservationMethod = ObservationMethod.RENDERED,
) -> ResponsiveObservation:
    return ResponsiveObservation(
        breakpoint=breakpoint,
        viewport=Viewport(width=768, height=1024),
        status=EvidenceStatus.OBSERVED,
        style=style,
        provenance=[_provenance(method=method, viewport=breakpoint)],
    )


def test_a_property_absent_from_the_delta_keeps_its_desktop_value() -> None:
    """A rendered crawl records responsive styles as changes from desktop, so a
    property absent from the delta was measured and found equal. Replacing the
    whole set instead of merging discarded every unchanged property, and spacing
    scored at desktop only while tablet and mobile were measured and thrown away.
    """

    section = _section(
        style=_named_style(padding="48px", row_gap="16px"),
        responsive=[_responsive_style(BreakpointName.TABLET, _named_style(width="752px"))],
    )

    desktop = _observe(section, BreakpointName.DESKTOP).spacing.spacing
    tablet = _observe(section, BreakpointName.TABLET).spacing.spacing

    assert desktop.padding_top == 48.0
    assert tablet.padding_top == 48.0
    assert tablet.element_gap == 16.0


def test_a_measured_change_overrides_the_desktop_value() -> None:
    section = _section(
        style=_named_style(padding="48px"),
        responsive=[_responsive_style(BreakpointName.MOBILE, _named_style(padding="16px"))],
    )

    assert _observe(section, BreakpointName.DESKTOP).spacing.spacing.padding_top == 48.0
    assert _observe(section, BreakpointName.MOBILE).spacing.spacing.padding_top == 16.0


def test_a_non_rendered_responsive_observation_is_not_merged() -> None:
    """Only the rendered adapter computes the delta. Absence means nothing
    elsewhere, and importing desktop values would be a cross-viewport borrow."""

    section = _section(
        style=_named_style(padding="48px"),
        responsive=[
            _responsive_style(
                BreakpointName.MOBILE,
                _named_style(width="374px"),
                method=ObservationMethod.INFERRED,
            )
        ],
    )

    assert _observe(section, BreakpointName.MOBILE).spacing.spacing.padding_top == 48.0


def test_a_breakpoint_with_no_observation_still_reads_the_base_style() -> None:
    section = _section(style=_named_style(padding="48px"), responsive=[])

    assert _observe(section, BreakpointName.MOBILE).spacing.spacing.padding_top == 48.0


# --- Figma geometry and media (RT-27, RT-29) -----------------------------------

# A Figma node reports canvas coordinates, so the page frame sits far from the
# origin and every section box must be shifted back to it.
_FRAME = BoundingBox(x=-3884, y=-513, width=1440, height=8090)


def _figma_provenance(
    bounds: BoundingBox | None,
    *,
    method: ObservationMethod = ObservationMethod.API,
    viewport: BreakpointName | None = BreakpointName.DESKTOP,
    inference: str | None = None,
    element_node_id: str = "156:900",
    frame_node_id: str = "156:890",
) -> Provenance:
    return Provenance(
        source_kind=SourceKind.FIGMA,
        method=method,
        viewport=viewport,
        file_key="file",
        frame_node_id=frame_node_id,
        element_node_id=element_node_id,
        bounds=bounds,
        metadata={"inference": inference} if inference else {},
    )


def _figma_page(sections: list[Section], frame: BoundingBox | None = _FRAME) -> Page:
    page = _page(sections)
    if frame is not None:
        page = page.model_copy(
            update={
                "provenance": [
                    _figma_provenance(frame, element_node_id="156:890", frame_node_id="156:890")
                ]
            }
        )
    return page


def _figma_bounds(
    section: Section,
    frame: BoundingBox | None = _FRAME,
    breakpoint: BreakpointName = BreakpointName.DESKTOP,
):
    page = _figma_page([section], frame)
    observation = observe_expected_page(page, _document(page), breakpoint)
    assert observation is not None
    return observation.sections[0].geometry.bounds


def test_an_inferred_figma_section_box_is_placed_relative_to_the_page_frame() -> None:
    # The grouping is inferred but the box is the union of boxes the API
    # measured, so it is real geometry once it is moved into page coordinates.
    section = _section(
        provenance=[
            _figma_provenance(
                BoundingBox(x=-3884, y=-382, width=1440, height=664),
                method=ObservationMethod.INFERRED,
                inference="flat_geometry",
            )
        ]
    )

    box = _figma_bounds(section)

    assert (box.x, box.y, box.width, box.height) == (0, 131, 1440, 664)


@pytest.mark.parametrize("inference", ["flat_geometry", "background_band", "whitespace_geometry"])
def test_every_measured_boundary_kind_carries_geometry(inference: str) -> None:
    section = _section(
        provenance=[
            _figma_provenance(
                BoundingBox(x=-3884, y=-382, width=1440, height=664),
                method=ObservationMethod.INFERRED,
                inference=inference,
            )
        ]
    )

    assert _figma_bounds(section) is not None


def test_an_inferred_figma_layout_record_is_still_not_geometry() -> None:
    # `geometry_layout` states a guessed layout, with no measured box behind it.
    section = _section(
        provenance=[
            _figma_provenance(
                BoundingBox(x=-3884, y=-382, width=1440, height=664),
                method=ObservationMethod.INFERRED,
                inference="geometry_layout",
            )
        ]
    )

    assert _figma_bounds(section) is None


def test_a_designed_figma_section_is_also_placed_relative_to_the_page_frame() -> None:
    section = _section(
        provenance=[_figma_provenance(BoundingBox(x=-3884, y=-413, width=1440, height=500))]
    )

    box = _figma_bounds(section)

    assert (box.x, box.y, box.width, box.height) == (0, 100, 1440, 500)


def test_a_section_hanging_past_the_frame_is_clipped_to_it() -> None:
    # A rotated banner or a carousel runs past the frame edge; a rendered page
    # cannot be wider than its viewport, so the overhang is not part of the box.
    section = _section(
        provenance=[
            _figma_provenance(
                BoundingBox(x=-3915, y=173, width=1471, height=286),
                method=ObservationMethod.INFERRED,
                inference="flat_geometry",
            )
        ]
    )

    box = _figma_bounds(section)

    assert (box.x, box.width) == (0, 1440)


def test_a_figma_box_with_no_page_frame_stays_unavailable() -> None:
    # Canvas coordinates against page coordinates would read as a gross
    # mismatch that nobody measured.
    section = _section(
        provenance=[_figma_provenance(BoundingBox(x=-3884, y=-413, width=1440, height=500))]
    )

    assert _figma_bounds(section, frame=None) is None


def test_a_figma_box_wholly_outside_the_frame_stays_unavailable() -> None:
    section = _section(
        provenance=[_figma_provenance(BoundingBox(x=-3884, y=9000, width=1440, height=500))]
    )

    assert _figma_bounds(section) is None


def test_a_figma_frame_is_only_used_for_the_breakpoint_it_draws() -> None:
    section = _section(
        provenance=[
            _figma_provenance(
                BoundingBox(x=100, y=0, width=390, height=300), viewport=BreakpointName.MOBILE
            )
        ]
    )

    # Only the desktop frame is on the page, so a mobile box cannot be placed.
    assert _figma_bounds(section, breakpoint=BreakpointName.MOBILE) is None


def _figma_image(
    key: str,
    order: int,
    asset_id: str,
    bounds: BoundingBox | None,
    *,
    role: str = "section_media",
) -> ContentElement:
    return _element(key, order, ContentKind.IMAGE, asset_id=asset_id).model_copy(
        update={"role": role, "provenance": [_figma_provenance(bounds)] if bounds else []}
    )


def _shared_asset() -> AssetRecord:
    # Figma records an image's size from the first node that used it: here the
    # banner's background, 1496 x 503.
    return AssetRecord(
        id="shared",
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        source_url="figma://file/ref",
        width=1496,
        height=503,
    )


def test_a_shared_asset_is_judged_by_each_elements_own_frame() -> None:
    poster = _figma_image("poster", 0, "shared", BoundingBox(x=0, y=0, width=902, height=493))
    background = _figma_image(
        "banner",
        0,
        "shared",
        BoundingBox(x=0, y=0, width=1496, height=503),
        role="background_media",
    )

    poster_media = _observe(_section(content=[poster]), assets={"shared": _shared_asset()}).media
    banner_media = _observe(
        _section(content=[background]), assets={"shared": _shared_asset()}
    ).media

    assert poster_media.media["media_1"].aspect_ratio == pytest.approx(902 / 493)
    assert banner_media.media["background_1"].aspect_ratio == pytest.approx(1496 / 503)


def test_an_image_with_no_figma_frame_keeps_the_asset_size() -> None:
    element = _figma_image("poster", 0, "shared", None)

    media = _observe(_section(content=[element]), assets={"shared": _shared_asset()}).media

    assert media.media["media_1"].aspect_ratio == pytest.approx(1496 / 503)


def test_a_frame_drawn_for_another_breakpoint_is_not_this_breakpoints_shape() -> None:
    element = _figma_image("poster", 0, "shared", BoundingBox(x=0, y=0, width=902, height=493))

    media = _observe(
        _section(content=[element]),
        BreakpointName.MOBILE,
        assets={"shared": _shared_asset()},
    ).media

    assert media.media["media_1"].aspect_ratio == pytest.approx(1496 / 503)


def test_a_live_html_rendered_image_box_does_not_replace_the_asset_size() -> None:
    # Live pages keep their asset-size behaviour; only Figma records a shared
    # asset's size from its first owner.
    element = _element("img", 0, ContentKind.IMAGE, asset_id="shared").model_copy(
        update={
            "provenance": [
                _provenance(
                    viewport=BreakpointName.DESKTOP,
                    bounds=BoundingBox(x=0, y=0, width=300, height=300),
                )
            ]
        }
    )

    media = _observe(_section(content=[element]), assets={"shared": _shared_asset()}).media

    assert media.media["media_1"].aspect_ratio == pytest.approx(1496 / 503)


def test_a_background_photo_is_its_own_slot_and_does_not_shift_image_numbering() -> None:
    # The build paints the background as CSS, not an <img>, so numbering it
    # among the images would put every later image out of step with the render.
    photo = AssetRecord(
        id="photo",
        kind=AssetKind.IMAGE,
        role=AssetRole.EDITORIAL,
        source_url="figma://file/photo",
        width=400,
        height=400,
    )
    background = _figma_image(
        "bg", 0, "shared", BoundingBox(x=0, y=0, width=1440, height=664), role="background_media"
    )
    mascot = _figma_image("mascot", 1, "photo", BoundingBox(x=0, y=0, width=400, height=400))

    media = _observe(
        _section(content=[background, mascot]), assets={"shared": _shared_asset(), "photo": photo}
    ).media

    assert set(media.media) == {"background_1", "media_1"}
    assert media.media["media_1"].aspect_ratio == pytest.approx(1.0)


def test_a_figma_page_tolerates_vertical_offset_at_the_breakpoint_it_draws() -> None:
    page = _figma_page([_section()])

    desktop = observe_expected_page(page, _document(page), BreakpointName.DESKTOP)
    mobile = observe_expected_page(page, _document(page), BreakpointName.MOBILE)

    # Only a desktop frame is on the page, so mobile has nothing to be lenient about.
    assert desktop is not None and desktop.vertical_offset_tolerated is True
    assert mobile is not None and mobile.vertical_offset_tolerated is False


def test_a_live_html_page_keeps_comparing_absolute_positions() -> None:
    # A rendered crawl of the source is not one static frame, and its recorded
    # scores must not move when this tolerance is introduced for Figma.
    page = _page([_section()])

    observation = observe_expected_page(page, _document(page), BreakpointName.DESKTOP)

    assert observation is not None
    assert observation.vertical_offset_tolerated is False
