"""Contracts for deriving observed fidelity observations from a rendered build."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vanjaro_cli.design.fidelity_color import ColorRole
from vanjaro_cli.design.fidelity_evaluation import PageObservation, score_breakpoint_fidelity
from vanjaro_cli.design.fidelity_extraction import observe_expected_page
from vanjaro_cli.design.fidelity_layout import BoundingBox
from vanjaro_cli.design.fidelity_observation import (
    RenderedMedia,
    RenderedPage,
    RenderedSection,
    RenderedText,
    observe_built_page,
    observe_built_section,
)
from vanjaro_cli.design.models import (
    AssetKind,
    AssetRecord,
    AssetRole,
    BoundingBox as SourceBox,
    BreakpointName,
    ContentElement,
    ContentKind,
    DesignAnalysis,
    DesignDocument,
    DesignSource,
    DesignTokens,
    LayoutKind,
    LayoutObservation,
    NavigationVisibility,
    ObservationMethod,
    Page,
    Provenance,
    Section,
    SourceKind,
    StyleObservation,
    StyleProperty,
    StyleSet,
)


def _section(**overrides) -> RenderedSection:
    defaults = {
        "section_id": "home.section.1",
        "order": 0,
        "bounds": BoundingBox(x=0, y=0, width=1440, height=560),
        "columns": 3,
    }
    return RenderedSection(**{**defaults, **overrides})


def test_geometry_and_columns_pass_through_unchanged() -> None:
    observation = observe_built_section(_section())

    assert observation.geometry.section_id == "home.section.1"
    assert observation.geometry.bounds is not None
    assert observation.geometry.bounds.width == 1440
    assert observation.geometry.columns == 3


def test_unmeasured_geometry_stays_unavailable() -> None:
    observation = observe_built_section(_section(bounds=None, columns=None))

    assert observation.geometry.bounds is None
    assert observation.geometry.columns is None


def test_palette_carries_only_the_colours_actually_measured() -> None:
    observation = observe_built_section(
        _section(background_color="#ffffff", accent_color="  #ff5500  ")
    )

    assert observation.palette.get(ColorRole.BACKGROUND) == "#ffffff"
    assert observation.palette.get(ColorRole.ACCENT) == "#ff5500"
    assert observation.palette.get(ColorRole.TEXT) is None


def test_blank_colour_strings_are_not_treated_as_measurements() -> None:
    observation = observe_built_section(_section(background_color="   "))

    assert observation.palette.get(ColorRole.BACKGROUND) is None


def test_typography_keys_match_the_expected_side() -> None:
    observation = observe_built_section(
        _section(
            typography={
                "heading": RenderedText(family="Inter", size_px=48, weight=700),
                "body": RenderedText(family="Inter", size_px=16),
            }
        )
    )

    assert set(observation.typography.samples) == {"heading", "body"}
    assert observation.typography.samples["heading"].size_px == 48
    assert observation.typography.samples["body"].weight is None


def test_refused_font_substitution_is_carried_through_not_scored_as_a_mismatch() -> None:
    observation = observe_built_section(
        _section(typography={"heading": RenderedText(substitution_refused=True)})
    )

    assert observation.typography.samples["heading"].substitution_refused is True


def test_measured_zero_padding_is_evidence_not_absence() -> None:
    observation = observe_built_section(_section(padding_top=0, padding_bottom=0))

    assert observation.spacing.spacing.padding_top == 0.0
    assert observation.spacing.spacing.padding_bottom == 0.0


def test_unmeasured_spacing_stays_unavailable() -> None:
    observation = observe_built_section(_section())

    assert observation.spacing.spacing.padding_top is None
    assert observation.spacing.spacing.element_gap is None


def test_media_is_numbered_in_document_order_to_match_the_expected_side() -> None:
    observation = observe_built_section(
        _section(
            media=[
                RenderedMedia(rendered_width=800, rendered_height=450),
                RenderedMedia(rendered_width=400, rendered_height=400),
            ]
        )
    )

    assert set(observation.media.media) == {"media_1", "media_2"}
    assert observation.media.media["media_1"].aspect_ratio == pytest.approx(16 / 9)
    assert observation.media.media["media_2"].aspect_ratio == pytest.approx(1.0)


def test_crop_coverage_needs_the_intrinsic_size() -> None:
    without = observe_built_section(
        _section(media=[RenderedMedia(rendered_width=800, rendered_height=450)])
    )

    assert without.media.media["media_1"].crop_coverage is None


def test_crop_coverage_reports_the_visible_fraction_of_a_cropped_source() -> None:
    # A 1:1 source shown in a 16:9 box keeps 9/16 of its longer axis.
    observation = observe_built_section(
        _section(
            media=[
                RenderedMedia(
                    rendered_width=1600,
                    rendered_height=900,
                    natural_width=1000,
                    natural_height=1000,
                )
            ]
        )
    )

    assert observation.media.media["media_1"].crop_coverage == pytest.approx(0.5625)


def test_an_uncropped_image_keeps_full_coverage() -> None:
    observation = observe_built_section(
        _section(
            media=[
                RenderedMedia(
                    rendered_width=1600,
                    rendered_height=900,
                    natural_width=800,
                    natural_height=450,
                )
            ]
        )
    )

    assert observation.media.media["media_1"].crop_coverage == pytest.approx(1.0)


@pytest.mark.parametrize("loaded", [True, False, None])
def test_whether_an_image_loaded_is_carried_to_its_media_sample(loaded: bool | None) -> None:
    observation = observe_built_section(
        _section(media=[RenderedMedia(rendered_width=800, rendered_height=450, loaded=loaded)])
    )

    assert observation.media.media["media_1"].loaded is loaded


def test_a_css_background_photo_does_not_report_loading() -> None:
    observation = observe_built_section(
        _section(background_media=RenderedMedia(rendered_width=1440, rendered_height=664))
    )

    assert observation.media.media["background_1"].loaded is None


def test_integrity_is_measured_on_the_build_including_page_level_console_errors() -> None:
    observation = observe_built_section(
        _section(
            horizontal_overflow_px=12,
            empty_slot_count=2,
            placeholder_leaks=("Lorem ipsum",),
        ),
        console_error_count=3,
    )

    assert observation.integrity is not None
    assert observation.integrity.horizontal_overflow_px == 12
    assert observation.integrity.empty_slot_count == 2
    assert observation.integrity.console_error_count == 3
    assert observation.integrity.placeholder_leaks == ("Lorem ipsum",)


def test_page_observation_orders_sections_and_keeps_the_measured_viewport() -> None:
    page = RenderedPage(
        viewport_width=390,
        sections=(
            _section(section_id="home.section.2", order=1),
            _section(section_id="home.section.1", order=0),
        ),
    )

    observation = observe_built_page(page)

    assert observation is not None
    assert observation.viewport_width == 390
    assert [item.section_id for item in observation.sections] == [
        "home.section.1",
        "home.section.2",
    ]


def test_a_page_with_no_measured_sections_produces_no_observation() -> None:
    # An empty render is a capture failure for the gate to report, not a page
    # that legitimately scores zero.
    assert observe_built_page(RenderedPage(viewport_width=1440)) is None


def test_observation_is_deterministic() -> None:
    page = RenderedPage(viewport_width=1440, sections=(_section(),))

    first = observe_built_page(page)
    second = observe_built_page(page)

    assert first is not None and second is not None
    assert first.model_dump_json() == second.model_dump_json()


def _design_page():
    """A one-section design with geometry, colour, type, and spacing evidence."""

    provenance = Provenance(
        source_kind=SourceKind.LIVE_HTML,
        method=ObservationMethod.RENDERED,
        source_url="https://agency.example/",
        viewport=BreakpointName.DESKTOP,
        bounds=SourceBox(x=0, y=0, width=1440, height=560),
    )
    heading = ContentElement(
        id="h",
        order=1,
        kind=ContentKind.HEADING,
        role="section_title",
        value="Services",
        style=StyleSet(
            observations=[
                StyleObservation(property=StyleProperty.FONT_FAMILY, value="Inter"),
                StyleObservation(property=StyleProperty.FONT_SIZE, value="48px"),
                StyleObservation(property=StyleProperty.FONT_WEIGHT, value=700),
            ]
        ),
        provenance=[],
        confidence=1,
    )
    section = Section(
        id="home.s1",
        order=0,
        semantic_role="feature_cards",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=True, columns=3),
        content=[heading],
        groups=[],
        style=StyleSet(
            observations=[
                StyleObservation(property=StyleProperty.BACKGROUND_COLOR, value="#ffffff"),
                StyleObservation(property=StyleProperty.TEXT_COLOR, value="#111111"),
                StyleObservation(property=StyleProperty.PADDING, value="64px 0"),
            ]
        ),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[provenance],
    )
    page = Page(
        id="home",
        source_reference="https://agency.example/",
        title="Home",
        slug="home",
        sections=[section],
        breakpoints=[BreakpointName.DESKTOP],
        navigation_visibility=NavigationVisibility.VISIBLE,
        provenance=[],
    )
    document = DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.LIVE_HTML,
            identifier="https://agency.example/",
            captured_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            adapter_version="1.0.0",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[page],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )
    return observe_expected_page(page, document, BreakpointName.DESKTOP)


def _built(**overrides):
    defaults = {
        "section_id": "home.s1",
        "order": 0,
        "columns": 3,
        "bounds": BoundingBox(x=0, y=0, width=1440, height=560),
        "background_color": "#ffffff",
        "text_color": "#111111",
        "typography": {"heading": RenderedText(family="Inter", size_px=48, weight=700)},
        "padding_top": 64,
        "padding_bottom": 64,
        "horizontal_overflow_px": 0,
        "empty_slot_count": 0,
    }
    return observe_built_page(
        RenderedPage(
            viewport_width=1440,
            console_error_count=overrides.pop("console_error_count", 0),
            sections=(RenderedSection(**{**defaults, **overrides}),),
        )
    )


def _score(built):
    return score_breakpoint_fidelity(
        _design_page(), built, breakpoint=BreakpointName.DESKTOP
    )


def test_a_faithful_build_scores_full_marks_end_to_end() -> None:
    result = _score(_built())

    assert result.overall_score == 100.0
    assert result.unmeasured_section_ids == ()


def test_a_degraded_build_scores_zero_end_to_end() -> None:
    result = _score(
        _built(
            columns=1,
            bounds=BoundingBox(x=0, y=200, width=900, height=300),
            background_color="#000000",
            text_color="#888888",
            typography={"heading": RenderedText(family="Arial", size_px=20, weight=400)},
            padding_top=0,
            padding_bottom=0,
            horizontal_overflow_px=40,
            empty_slot_count=3,
            placeholder_leaks=("Lorem ipsum",),
            console_error_count=4,
        )
    )

    # Placeholder leakage forces zero regardless of the other dimensions.
    assert result.overall_score == 0.0


def test_a_section_that_was_never_built_fails_every_comparable_dimension() -> None:
    result = _score(
        observe_built_page(
            RenderedPage(
                viewport_width=1440,
                sections=(RenderedSection(section_id="unrelated", order=0),),
            )
        )
    )

    scored = {entry.dimension.value: entry.score for entry in result.sections[0].dimensions}
    assert result.overall_score == 0.0
    assert scored == {
        "layout": 0.0,
        "color": 0.0,
        "typography": 0.0,
        "spacing": 0.0,
        "media": 0.0,
        "copy": 0.0,
    }


def test_a_dimension_without_evidence_stays_unmeasured_rather_than_zero() -> None:
    # No media exists on either side, so media must drop out of the mean
    # instead of scoring zero and dragging a faithful build down.
    result = _score(_built())
    media = next(
        entry for entry in result.sections[0].dimensions if entry.dimension.value == "media"
    )

    assert media.score is None


def test_a_css_background_photo_is_keyed_apart_from_the_images() -> None:
    observation = observe_built_section(
        _section(
            media=[RenderedMedia(rendered_width=400, rendered_height=400)],
            background_media=RenderedMedia(rendered_width=1440, rendered_height=664),
        )
    )

    assert set(observation.media.media) == {"media_1", "background_1"}
    assert observation.media.media["media_1"].aspect_ratio == pytest.approx(1.0)
    assert observation.media.media["background_1"].aspect_ratio == pytest.approx(1440 / 664)


def test_a_section_without_a_background_photo_reports_no_background_slot() -> None:
    assert "background_1" not in observe_built_section(_section()).media.media


# --- A Figma hero built far shorter than designed (RT-29) ----------------------


def _figma_hero_design():
    frame = SourceBox(x=-3884, y=-513, width=1440, height=8090)
    frame_record = Provenance(
        source_kind=SourceKind.FIGMA,
        method=ObservationMethod.API,
        viewport=BreakpointName.DESKTOP,
        frame_node_id="156:890",
        element_node_id="156:890",
        bounds=frame,
    )
    hero_record = Provenance(
        source_kind=SourceKind.FIGMA,
        method=ObservationMethod.INFERRED,
        viewport=BreakpointName.DESKTOP,
        frame_node_id="156:890",
        element_node_id="156:890:inferred-2",
        bounds=SourceBox(x=-3884, y=-382, width=1440, height=664),
        metadata={"inference": "flat_geometry"},
    )
    background = ContentElement(
        id="hero.bg",
        order=0,
        kind=ContentKind.IMAGE,
        role="background_media",
        asset_id="hero-photo",
        provenance=[
            Provenance(
                source_kind=SourceKind.FIGMA,
                method=ObservationMethod.API,
                viewport=BreakpointName.DESKTOP,
                frame_node_id="156:890",
                element_node_id="156:909",
                bounds=SourceBox(x=-3884, y=-382, width=1440, height=664),
            )
        ],
        confidence=1,
    )
    section = Section(
        id="home.hero",
        order=0,
        semantic_role="hero",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=False, columns=1),
        content=[background],
        groups=[],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[hero_record],
    )
    banner = section.model_copy(
        update={
            "id": "home.cta",
            "order": 1,
            "semantic_role": "call_to_action",
            "content": [],
            "provenance": [
                hero_record.model_copy(
                    update={"bounds": SourceBox(x=-3884, y=282, width=1440, height=500)}
                )
            ],
        }
    )
    page = Page(
        id="home",
        source_reference="156:890",
        title="Home",
        slug="home",
        sections=[section, banner],
        breakpoints=[BreakpointName.DESKTOP],
        navigation_visibility=NavigationVisibility.UNKNOWN,
        provenance=[frame_record],
    )
    document = DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA,
            identifier="file",
            captured_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
            adapter_version="1.0.0",
        ),
        tokens=DesignTokens(),
        assets=[
            AssetRecord(
                id="hero-photo",
                kind=AssetKind.IMAGE,
                role=AssetRole.EDITORIAL,
                source_url="figma://file/ref",
                width=1440,
                height=664,
            )
        ],
        pages=[page],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )
    return observe_expected_page(page, document, BreakpointName.DESKTOP)


def _built_hero(*, y: float, height: float, background: bool = True):
    return observe_built_page(
        RenderedPage(
            viewport_width=1440,
            sections=(
                RenderedSection(
                    section_id="home.hero",
                    order=0,
                    columns=1,
                    bounds=BoundingBox(x=0, y=y, width=1440, height=height),
                    background_media=(
                        RenderedMedia(rendered_width=1440, rendered_height=height)
                        if background
                        else None
                    ),
                ),
            ),
        )
    )


def _dimensions(built, section_id: str = "home.hero") -> dict[str, float | None]:
    result = score_breakpoint_fidelity(
        _figma_hero_design(), built, breakpoint=BreakpointName.DESKTOP
    )
    section = next(entry for entry in result.sections if entry.section_id == section_id)
    return {entry.dimension.value: entry.score for entry in section.dimensions}


def test_a_hero_built_as_designed_scores_full_layout_and_media() -> None:
    scores = _dimensions(_built_hero(y=131, height=664))

    assert scores["layout"] == 100.0
    assert scores["media"] == 100.0


def test_a_hero_built_152px_tall_instead_of_664_loses_layout_as_well_as_media() -> None:
    # Before the design side carried a section box, the height was never
    # compared and this section kept a perfect layout score.
    faithful = _dimensions(_built_hero(y=131, height=664))
    short = _dimensions(_built_hero(y=53, height=152))

    assert short["layout"] < 60.0
    assert short["layout"] < faithful["layout"]
    # The photo is present, so media is credited, but at the wrong shape.
    assert 0.0 < short["media"] < faithful["media"]


def test_a_hero_with_its_photo_missing_still_scores_media_zero() -> None:
    scores = _dimensions(_built_hero(y=131, height=664, background=False))

    assert scores["media"] == 0.0


def _built_hero_and_banner(*, hero_height: float, banner_y: float, banner_order: int = 1):
    hero_order = 1 - banner_order
    return observe_built_page(
        RenderedPage(
            viewport_width=1440,
            sections=(
                RenderedSection(
                    section_id="home.hero",
                    order=hero_order,
                    columns=1,
                    bounds=BoundingBox(x=0, y=53, width=1440, height=hero_height),
                    background_media=RenderedMedia(
                        rendered_width=1440, rendered_height=hero_height
                    ),
                ),
                RenderedSection(
                    section_id="home.cta",
                    order=banner_order,
                    columns=1,
                    bounds=BoundingBox(x=0, y=banner_y, width=1440, height=500),
                ),
            ),
        )
    )


def test_a_short_hero_fails_its_own_section_but_not_the_one_below_it() -> None:
    # The banner is built at its designed height; it only sits higher because
    # the hero above it came out 512px short.
    built = _built_hero_and_banner(hero_height=152, banner_y=205)

    assert _dimensions(built, "home.hero")["layout"] < 60.0
    assert _dimensions(built, "home.cta")["layout"] == 100.0


def test_a_banner_built_too_short_still_fails_when_the_hero_is_right() -> None:
    built = observe_built_page(
        RenderedPage(
            viewport_width=1440,
            sections=(
                RenderedSection(
                    section_id="home.hero",
                    order=0,
                    columns=1,
                    bounds=BoundingBox(x=0, y=131, width=1440, height=664),
                    background_media=RenderedMedia(rendered_width=1440, rendered_height=664),
                ),
                RenderedSection(
                    section_id="home.cta",
                    order=1,
                    columns=1,
                    bounds=BoundingBox(x=0, y=795, width=1440, height=100),
                ),
            ),
        )
    )

    assert _dimensions(built, "home.hero")["layout"] == 100.0
    assert _dimensions(built, "home.cta")["layout"] < 60.0


def test_swapping_the_hero_and_the_banner_still_loses_layout_points() -> None:
    in_order = _built_hero_and_banner(hero_height=664, banner_y=795)
    swapped = _built_hero_and_banner(hero_height=664, banner_y=795, banner_order=0)

    for section_id in ("home.hero", "home.cta"):
        assert (
            _dimensions(swapped, section_id)["layout"]
            < _dimensions(in_order, section_id)["layout"]
        )


def test_the_tolerance_survives_the_recorded_evidence_round_trip() -> None:
    recorded = _figma_hero_design().model_dump(mode="json")

    assert PageObservation.model_validate(recorded).vertical_offset_tolerated is True


def test_evidence_recorded_before_the_tolerance_existed_compares_absolute_positions() -> None:
    recorded = _figma_hero_design().model_dump(mode="json")
    del recorded["vertical_offset_tolerated"]

    assert PageObservation.model_validate(recorded).vertical_offset_tolerated is False


# --- A Figma page scored on the colour and type its design states (RT-36) -------

_FIGMA_FRAME = SourceBox(x=-3884, y=-513, width=1440, height=8090)


def _figma_record(
    bounds: SourceBox, *, element_node_id: str, method: ObservationMethod = ObservationMethod.API
) -> Provenance:
    return Provenance(
        source_kind=SourceKind.FIGMA,
        method=method,
        viewport=BreakpointName.DESKTOP,
        frame_node_id="156:890",
        element_node_id=element_node_id,
        bounds=bounds,
        metadata={"inference": "flat_geometry"} if method is ObservationMethod.INFERRED else {},
    )


def _figma_text(
    element_id: str,
    order: int,
    kind: ContentKind,
    *,
    size: float,
    role: str = "section_title",
) -> ContentElement:
    return ContentElement(
        id=element_id,
        order=order,
        kind=kind,
        role=role,
        value="Copy",
        attributes={"font_family": "Mortina DEMO", "font_size": size, "font_weight": 400},
        provenance=[
            _figma_record(
                SourceBox(x=-3700, y=-300, width=600, height=100), element_node_id=element_id
            )
        ],
        confidence=1,
    )


def _figma_section(
    section_id: str,
    order: int,
    *,
    y: float,
    height: float,
    content: list[ContentElement],
    band_color: str | None = None,
) -> Section:
    band = {
        "role": "base",
        "color": band_color,
        "node_id": "1:1",
        "bounds": {"x": -3884, "y": y - 513, "width": 1440, "height": height},
    }
    return Section(
        id=section_id,
        order=order,
        semantic_role="hero" if order == 0 else "marquee",
        role_confidence=1,
        candidate_roles=[],
        layout=LayoutObservation(kind=LayoutKind.GRID, contained=False, columns=1),
        content=content,
        groups=[],
        style=StyleSet(),
        responsive=[],
        decorative_layers=[],
        interactions=[],
        provenance=[
            _figma_record(
                SourceBox(x=-3884, y=y - 513, width=1440, height=height),
                element_node_id=f"{section_id}:node",
                method=ObservationMethod.INFERRED,
            )
        ],
        metadata={"background_bands": [band]} if band_color else {},
    )


def _hero_and_marquee_design(*, band_color: str | None = "#f0709d"):
    sections = [
        _figma_section(
            "home.hero",
            0,
            y=0,
            height=664,
            content=[_figma_text("hero.title", 0, ContentKind.HEADING, size=80)],
        ),
        _figma_section(
            "home.marquee",
            1,
            y=664,
            height=286,
            content=[_figma_text("marquee.item", 0, ContentKind.LIST_ITEM, size=50, role="body")],
            band_color=band_color,
        ),
    ]
    page = Page(
        id="home",
        source_reference="156:890",
        title="Home",
        slug="home",
        sections=sections,
        breakpoints=[BreakpointName.DESKTOP],
        navigation_visibility=NavigationVisibility.UNKNOWN,
        provenance=[_figma_record(_FIGMA_FRAME, element_node_id="156:890")],
    )
    document = DesignDocument(
        schema_version="1.0",
        source=DesignSource(
            kind=SourceKind.FIGMA,
            identifier="file",
            captured_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
            adapter_version="1.0.0",
        ),
        tokens=DesignTokens(),
        assets=[],
        pages=[page],
        warnings=[],
        analysis=DesignAnalysis(section_confidence_mean=1.0, unsupported_traits=[]),
    )
    return observe_expected_page(page, document, BreakpointName.DESKTOP)


def _built_hero_and_marquee(
    *,
    heading_px: float = 80,
    marquee_background: str = "#f0709d",
):
    return observe_built_page(
        RenderedPage(
            viewport_width=1440,
            sections=(
                RenderedSection(
                    section_id="home.hero",
                    order=0,
                    columns=1,
                    bounds=BoundingBox(x=0, y=0, width=1440, height=664),
                    typography={"heading": RenderedText(size_px=heading_px, weight=400)},
                ),
                RenderedSection(
                    section_id="home.marquee",
                    order=1,
                    columns=1,
                    bounds=BoundingBox(x=0, y=664, width=1440, height=286),
                    background_color=marquee_background,
                    typography={"body": RenderedText(size_px=50, weight=400)},
                ),
            ),
        )
    )


def _figma_section_score(design, built, section_id: str):
    result = score_breakpoint_fidelity(design, built, breakpoint=BreakpointName.DESKTOP)
    section = next(entry for entry in result.sections if entry.section_id == section_id)
    return section.score, {entry.dimension.value: entry.score for entry in section.dimensions}


def test_a_figma_build_that_matches_its_colour_and_type_still_scores_full_marks() -> None:
    design = _hero_and_marquee_design()
    built = _built_hero_and_marquee()

    assert _figma_section_score(design, built, "home.hero")[0] == 100.0
    assert _figma_section_score(design, built, "home.marquee")[0] == 100.0


def test_a_hero_heading_built_at_half_the_designed_size_loses_typography_points() -> None:
    # Figma states the heading at 80px. Before regime 3 that size was never
    # read, typography was unmeasured, and a 40px heading kept a perfect hero.
    design = _hero_and_marquee_design()

    score, dimensions = _figma_section_score(
        design, _built_hero_and_marquee(heading_px=40), "home.hero"
    )

    assert dimensions["typography"] == pytest.approx(200 / 3, abs=0.01)
    assert score < 90.0


def test_a_band_painted_the_wrong_colour_loses_colour_points() -> None:
    # The design's pink band was measured as a base band; the build painted orange.
    design = _hero_and_marquee_design()

    score, dimensions = _figma_section_score(
        design, _built_hero_and_marquee(marquee_background="#fe6124"), "home.marquee"
    )

    assert dimensions["color"] == 0.0
    assert score < 70.0


def test_a_section_with_no_band_has_no_colour_evidence_rather_than_full_credit() -> None:
    design = _hero_and_marquee_design(band_color=None)

    _, dimensions = _figma_section_score(
        design, _built_hero_and_marquee(marquee_background="#fe6124"), "home.marquee"
    )

    assert dimensions["color"] is None
    assert dimensions["spacing"] is None
