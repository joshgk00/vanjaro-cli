"""RT-37 — what the browser reports becomes wording, cards, and darkening in the score."""

from __future__ import annotations

import pytest

from vanjaro_cli.design.fidelity_color import ColorRole, OverlaySample, SectionPalette
from vanjaro_cli.design.fidelity_copy import CopyExpectation, SectionCopy
from vanjaro_cli.design.fidelity_evaluation import (
    PageObservation,
    SectionObservation,
    score_breakpoint_fidelity,
)
from vanjaro_cli.design.fidelity_layout import BoundingBox, SectionGeometry
from vanjaro_cli.design.fidelity_measure import MEASURE_SCRIPT, parse_measured_page
from vanjaro_cli.design.fidelity_observation import (
    RenderedOverlayLayer,
    RenderedSection,
    RenderedSurface,
    RenderedTextRun,
    observe_built_page,
    observe_built_section,
)
from vanjaro_cli.design.models import BreakpointName

SECTION_ID = "home.section.5"
WHITE = "rgb(255, 255, 255)"
PINK = "rgb(240, 112, 157)"


def _payload(**overrides: object) -> dict:
    section = {
        "section_id": SECTION_ID,
        "order": 0,
        "bounds": {"x": 0, "y": 0, "width": 1440, "height": 600},
    }
    section.update(overrides)
    return {"sections": [section]}


def _observe(**overrides: object) -> SectionObservation:
    page = observe_built_page(parse_measured_page(_payload(**overrides), viewport_width=1440))
    assert page is not None
    return page.sections[0]


def _run(text: str, color: str = "rgb(34, 34, 34)", background: str | None = WHITE, over_image: bool = False) -> dict:
    return {"text": text, "color": color, "background": background, "over_image": over_image}


class TestLegibleText:
    def test_text_the_browser_rendered_becomes_the_sections_wording(self) -> None:
        wording = _observe(text_runs=[_run("Our Classes"), _run("Prelude")]).wording

        assert wording.rendered == "Our Classes Prelude"
        assert wording.expected == ()

    def test_white_text_on_a_white_card_is_in_the_page_but_not_in_the_wording(self) -> None:
        wording = _observe(
            text_runs=[_run("Opening Notes"), _run("Prelude", color=WHITE, background=WHITE)]
        ).wording

        assert wording.rendered == "Opening Notes"

    def test_text_a_few_shades_off_its_background_is_still_camouflaged(self) -> None:
        wording = _observe(
            text_runs=[_run("Prelude", color="rgb(254, 254, 254)", background=WHITE)]
        ).wording

        assert wording.rendered == ""

    def test_white_text_on_a_pale_yellow_card_is_poor_design_but_readable(self) -> None:
        wording = _observe(
            text_runs=[_run("Stats", color=WHITE, background="rgb(253, 187, 44)")]
        ).wording

        assert wording.rendered == "Stats"

    def test_fully_transparent_text_cannot_be_read(self) -> None:
        wording = _observe(text_runs=[_run("Ghost", color="rgba(34, 34, 34, 0)")]).wording

        assert wording.rendered == ""

    def test_whatever_the_page_could_not_pin_down_gets_the_benefit_of_the_doubt(self) -> None:
        wording = _observe(
            text_runs=[
                _run("Over a photo", color=WHITE, background=None, over_image=True),
                _run("Nothing painted", color=WHITE, background=None),
                _run("Translucent", color=WHITE, background="rgba(255, 255, 255, 0.5)"),
                _run("Odd colour", color="oklch(0.7 0.1 200)", background=WHITE),
            ]
        ).wording

        assert wording.rendered == "Over a photo Nothing painted Translucent Odd colour"

    def test_a_measurement_with_no_text_runs_reports_nothing_rather_than_an_empty_page(self) -> None:
        assert _observe().wording.rendered is None
        assert _observe(text_runs=[]).wording.rendered == ""

    def test_blank_and_malformed_runs_are_dropped(self) -> None:
        wording = _observe(text_runs=[_run("   "), "nope", {"text": 4}, _run("Kept")]).wording

        assert wording.rendered == "Kept"


class TestCardsAndDarkening:
    def _surface(self, color: str = PINK, **overrides: object) -> dict:
        record = {"color": color, "x": 100, "y": 100, "width": 300, "height": 400, "has_text": True}
        record.update(overrides)
        return record

    def test_painted_boxes_become_cards_by_the_design_sides_rules(self) -> None:
        palette = _observe(
            surfaces=[
                self._surface(),
                self._surface("rgb(253, 187, 44)", x=500),
                self._surface("rgb(16, 48, 48)", x=0, y=0, width=1440, height=600),  # the band
                self._surface("rgb(0, 0, 0)", has_text=False),
                self._surface("rgba(1, 2, 3, 0.5)", x=900),  # not opaque
            ]
        ).palette

        assert palette.surfaces == ("#f0709d", "#fdbb2c")

    def test_no_painted_boxes_is_a_measurement_not_an_absence(self) -> None:
        assert _observe(surfaces=[]).palette.surfaces == ()
        assert _observe().palette.surfaces is None

    def test_cards_cannot_be_judged_without_the_sections_size(self) -> None:
        assert _observe(bounds=None, surfaces=[self._surface()]).palette.surfaces is None

    def test_a_translucent_layer_over_most_of_the_section_is_its_darkening(self) -> None:
        overlay = _observe(
            overlay_layers=[
                {"color": "rgba(0, 0, 0, 0.4)", "coverage": 1.0},
                {"color": "rgba(255, 0, 0, 0.9)", "coverage": 0.2},
                {"color": "rgba(0, 0, 0, 0)", "coverage": 1.0},
                {"color": "rgb(0, 0, 0)", "coverage": 1.0},
            ]
        ).palette.overlay

        assert overlay == OverlaySample(present=True, color="#000000", opacity=0.4)

    def test_the_strongest_covering_layer_wins(self) -> None:
        overlay = _observe(
            overlay_layers=[
                {"color": "rgba(0, 0, 0, 0.2)", "coverage": 0.9},
                {"color": "rgba(16, 48, 48, 0.6)", "coverage": 0.9},
            ]
        ).palette.overlay

        assert overlay == OverlaySample(present=True, color="#103030", opacity=0.6)

    def test_looking_and_finding_no_layer_is_reported_as_absent(self) -> None:
        assert _observe(overlay_layers=[]).palette.overlay == OverlaySample(present=False)
        assert _observe(overlay_layers=[{"color": "rgba(0, 0, 0, 0.4)", "coverage": 0.2}]).palette.overlay == OverlaySample(present=False)
        assert _observe().palette.overlay is None


class TestThroughTheScorer:
    def _designed(self, *lines: str, surfaces: tuple[str, ...] | None = None,
                  overlay: OverlaySample | None = None) -> PageObservation:
        return PageObservation(
            viewport_width=1440,
            sections=(
                SectionObservation(
                    geometry=SectionGeometry(
                        section_id=SECTION_ID, order=0,
                        bounds=BoundingBox(x=0, y=0, width=1440, height=600), columns=None,
                    ),
                    palette=SectionPalette(surfaces=surfaces, overlay=overlay),
                    wording=SectionCopy(expected=tuple(CopyExpectation(text=line) for line in lines)),
                ),
            ),
        )

    def _score(self, designed: PageObservation, built: PageObservation):
        scored = score_breakpoint_fidelity(designed, built, breakpoint=BreakpointName.DESKTOP)
        return scored.sections[0]

    def _built(self, **overrides: object) -> PageObservation:
        built = observe_built_page(parse_measured_page(_payload(**overrides), viewport_width=1440))
        assert built is not None
        return built

    def test_a_card_title_set_white_on_a_white_card_costs_the_section_points(self) -> None:
        designed = self._designed("Prelude", "Opening Notes", "Finale", "Symphony")
        built = self._built(
            text_runs=[
                _run("Prelude", color=WHITE, background=WHITE),
                _run("Opening Notes"),
                _run("Finale", color=WHITE, background=PINK),
                _run("Symphony"),
            ]
        )

        section = self._score(designed, built)
        copy = next(entry for entry in section.dimensions if entry.dimension.value == "copy")

        assert copy.score == 75.0
        assert "'Prelude'" in (copy.detail or "")
        assert section.score is not None and section.score < 100.0

    def test_a_faithful_build_scores_full_marks_on_wording_cards_and_darkening(self) -> None:
        overlay = OverlaySample(present=True, color="#000000", opacity=0.4)
        designed = self._designed(
            "Prelude", surfaces=("#f0709d",), overlay=overlay,
        )
        built = self._built(
            text_runs=[_run("Prelude")],
            surfaces=[{"color": PINK, "x": 100, "y": 100, "width": 300, "height": 400, "has_text": True}],
            overlay_layers=[{"color": "rgba(0, 0, 0, 0.4)", "coverage": 1.0}],
        )

        section = self._score(designed, built)

        assert section.score == 100.0

    def test_a_section_the_build_never_made_loses_its_wording_too(self) -> None:
        designed = self._designed("Prelude")
        unrelated = PageObservation(
            viewport_width=1440,
            sections=(observe_built_section(RenderedSection(section_id="other", order=0)),),
        )

        section = self._score(designed, unrelated)

        assert {entry.dimension.value: entry.score for entry in section.dimensions}["copy"] == 0.0

    def test_a_design_with_no_wording_adds_no_copy_dimension(self) -> None:
        section = self._score(self._designed(), self._built(text_runs=[_run("Anything")]))

        assert "copy" not in {entry.dimension.value for entry in section.dimensions}

    def test_a_build_that_reports_no_text_leaves_wording_unmeasured_not_failed(self) -> None:
        section = self._score(self._designed("Prelude"), self._built())

        copy = next(entry for entry in section.dimensions if entry.dimension.value == "copy")
        assert copy.score is None
        assert copy.detail == "the build did not report its rendered text"


class TestMeasureScript:
    """The page reports raw facts; these are the three it must now report."""

    def test_the_script_reports_text_runs_painted_boxes_and_translucent_layers(self) -> None:
        for key in ("text_runs: textRuns(node)", "surfaces: surfaceCandidates(node)", "overlay_layers: overlayLayers(node)"):
            assert key in MEASURE_SCRIPT

    def test_text_that_is_not_rendered_never_reaches_python(self) -> None:
        start = MEASURE_SCRIPT.index("const textRuns")
        body = MEASURE_SCRIPT[start : start + 1200]

        for guard in ("display === 'none'", "visibility === 'hidden'", "getClientRects", "SCRIPT|STYLE"):
            assert guard in body

    def test_the_script_leaves_the_legibility_judgement_to_python(self) -> None:
        start = MEASURE_SCRIPT.index("const textRuns")
        body = MEASURE_SCRIPT[start : start + 1200]

        assert "contrast" not in body.casefold()


class TestRenderedModels:
    def test_a_run_needs_text(self) -> None:
        with pytest.raises(ValueError):
            RenderedTextRun(text="")

    def test_a_layer_is_translucent_by_definition(self) -> None:
        with pytest.raises(ValueError):
            RenderedOverlayLayer(color="#000000", opacity=1.0, coverage=1.0)

    def test_a_surface_has_a_size(self) -> None:
        with pytest.raises(ValueError):
            RenderedSurface(color="#000000", x=0, y=0, width=0, height=10)


def test_roles_are_unchanged_for_a_section_the_build_painted_plainly() -> None:
    palette = _observe(background_color="rgb(255, 255, 255)").palette

    assert palette.colors == {ColorRole.BACKGROUND: "#ffffff"}
    assert palette.surfaces is None and palette.overlay is None
