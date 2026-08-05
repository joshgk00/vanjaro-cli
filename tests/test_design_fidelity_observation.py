"""Contracts for deriving observed fidelity observations from a rendered build."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from vanjaro_cli.design.fidelity_color import ColorRole
from vanjaro_cli.design.fidelity_evaluation import score_breakpoint_fidelity
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
    }


def test_a_dimension_without_evidence_stays_unmeasured_rather_than_zero() -> None:
    # No media exists on either side, so media must drop out of the mean
    # instead of scoring zero and dragging a faithful build down.
    result = _score(_built())
    media = next(
        entry for entry in result.sections[0].dimensions if entry.dimension.value == "media"
    )

    assert media.score is None
