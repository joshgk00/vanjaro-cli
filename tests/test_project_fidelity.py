"""VF-007 — fidelity gate wired into project verification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from vanjaro_cli.design.fidelity import CURRENT_REGIME_VERSION
from vanjaro_cli.design.fidelity_evaluation import (
    PageObservation,
    SectionObservation,
    score_breakpoint_fidelity,
    score_hook_from_observations,
)
from vanjaro_cli.design.fidelity_color import ColorRole, SectionPalette
from vanjaro_cli.design.fidelity_layout import SectionGeometry
from vanjaro_cli.design.fidelity_media import IntegrityObservation
from vanjaro_cli.design.models import BoundingBox, BreakpointName
from vanjaro_cli.orchestration.project_fidelity import (
    FIDELITY_EVIDENCE_PATH,
    ProjectFidelityError,
    evaluate_project_fidelity,
)

BREAKPOINTS = ("desktop", "tablet", "mobile")


def _section(
    section_id: str = "hero",
    *,
    y: float = 0,
    background: str = "#ffffff",
    leaks: tuple[str, ...] = (),
    with_integrity: bool = False,
) -> SectionObservation:
    integrity = None
    if with_integrity:
        integrity = IntegrityObservation(
            horizontal_overflow_px=0,
            empty_slot_count=0,
            console_error_count=0,
            placeholder_leaks=leaks,
        )
    return SectionObservation(
        geometry=SectionGeometry(
            section_id=section_id,
            order=0,
            bounds=BoundingBox(x=0, y=y, width=1440, height=600),
            columns=3,
        ),
        palette=SectionPalette(colors={ColorRole.BACKGROUND: background}),
        integrity=integrity,
    )


def _page(**kwargs: Any) -> PageObservation:
    return PageObservation(viewport_width=1440, sections=(_section(**kwargs),))


def _write_evidence(
    root: Path,
    *,
    expected: dict[str, Any] | None = None,
    observed: dict[str, Any] | None = None,
    captures: list[dict[str, Any]] | None = None,
    settled: bool = True,
) -> None:
    (root / "qa").mkdir(parents=True, exist_ok=True)
    if captures is None:
        captures = []
        for name in BREAKPOINTS:
            source = f"qa/{name}-source.png"
            output = f"qa/{name}-output.png"
            (root / source).write_bytes(b"png")
            (root / output).write_bytes(b"png")
            captures.append(
                {
                    "breakpoint": name,
                    "source_path": source,
                    "output_path": output,
                    "lazy_load_triggered": settled,
                    "fonts_settled": settled,
                    "animations_disabled": settled,
                }
            )
    payload = {
        "expected": expected if expected is not None else {},
        "observed": observed if observed is not None else {},
        "captures": captures,
    }
    (root / FIDELITY_EVIDENCE_PATH).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _all_breakpoints(page: PageObservation) -> dict[str, Any]:
    return {name: page.model_dump(mode="json") for name in BREAKPOINTS}


class TestPassingBuild:
    def test_matching_build_passes_the_draft_gate(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "scored"
        assert report["passed"] is True
        assert report["overall_score"] == 100.0
        assert blockers == []

    def test_report_carries_per_section_and_per_viewport_detail(
        self, tmp_path: Path
    ) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, _ = evaluate_project_fidelity(tmp_path)

        assert {entry["breakpoint"] for entry in report["viewport_scores"]} == set(
            BREAKPOINTS
        )
        assert [entry["section_id"] for entry in report["section_scores"]] == ["hero"]

    def test_report_is_json_serializable(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, _ = evaluate_project_fidelity(tmp_path)

        assert json.loads(json.dumps(report))["status"] == "scored"


class TestDegradedBuild:
    def test_shifted_and_recoloured_build_fails_the_gate(self, tmp_path: Path) -> None:
        expected = _page(with_integrity=True)
        degraded = _page(y=900, background="#101010", with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(expected),
            observed=_all_breakpoints(degraded),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["passed"] is False
        assert report["overall_score"] < 75
        assert any("visual fidelity gate failed" in blocker for blocker in blockers)

    def test_placeholder_leak_fails_an_otherwise_perfect_build(
        self, tmp_path: Path
    ) -> None:
        expected = _page(with_integrity=True)
        leaked = _page(with_integrity=True, leaks=("Lorem ipsum",))
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(expected),
            observed=_all_breakpoints(leaked),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["overall_score"] == 0.0
        assert report["passed"] is False
        assert blockers

    def test_missing_section_fails_the_gate(self, tmp_path: Path) -> None:
        expected = PageObservation(
            viewport_width=1440,
            sections=(_section("hero"), _section("cta")),
        )
        built = _page()
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(expected),
            observed=_all_breakpoints(built),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["passed"] is False
        assert blockers


class TestMissingEvidence:
    def test_absent_evidence_file_is_a_blocker_not_a_pass(self, tmp_path: Path) -> None:
        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers == [
            f"visual fidelity was not scored: no evidence recorded at {FIDELITY_EVIDENCE_PATH}"
        ]

    def test_evidence_without_observations_is_a_blocker(self, tmp_path: Path) -> None:
        _write_evidence(tmp_path)

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers

    def test_evidence_without_captures_is_a_blocker(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
            captures=[],
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert "no settled captures" in report["reason"]
        assert blockers

    def test_unsettled_captures_are_rejected(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
            settled=False,
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers

    def test_incomplete_breakpoints_are_rejected(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        only_desktop = {"desktop": page.model_dump(mode="json")}
        (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
        (tmp_path / "qa/desktop-source.png").write_bytes(b"png")
        (tmp_path / "qa/desktop-output.png").write_bytes(b"png")
        _write_evidence(
            tmp_path,
            expected=only_desktop,
            observed=only_desktop,
            captures=[
                {
                    "breakpoint": "desktop",
                    "source_path": "qa/desktop-source.png",
                    "output_path": "qa/desktop-output.png",
                    "lazy_load_triggered": True,
                    "fonts_settled": True,
                    "animations_disabled": True,
                }
            ],
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert blockers


class TestMalformedEvidence:
    def test_unknown_breakpoint_is_rejected(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected={"widescreen": page.model_dump(mode="json")},
            observed={"widescreen": page.model_dump(mode="json")},
        )

        with pytest.raises(ProjectFidelityError, match="unknown breakpoint"):
            evaluate_project_fidelity(tmp_path)

    def test_invalid_json_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "qa").mkdir(parents=True, exist_ok=True)
        (tmp_path / FIDELITY_EVIDENCE_PATH).write_text("{not json", encoding="utf-8")

        with pytest.raises(ProjectFidelityError, match="could not be read"):
            evaluate_project_fidelity(tmp_path)

    def test_invalid_observation_shape_is_rejected(self, tmp_path: Path) -> None:
        _write_evidence(
            tmp_path,
            expected={"desktop": {"viewport_width": -5, "sections": []}},
            observed={"desktop": {"viewport_width": 1440, "sections": []}},
        )

        with pytest.raises(ProjectFidelityError, match="are invalid"):
            evaluate_project_fidelity(tmp_path)


class TestEvaluationLayer:
    def test_section_absent_from_build_fails_every_dimension(self) -> None:
        expected = PageObservation(
            viewport_width=1440, sections=(_section("hero"), _section("cta"))
        )
        built = _page()

        scores = score_breakpoint_fidelity(
            expected, built, breakpoint=BreakpointName.DESKTOP
        )
        missing = next(s for s in scores.sections if s.section_id == "cta")

        assert missing.score == 0.0
        assert all(entry.score == 0.0 for entry in missing.dimensions)

    def test_scores_carry_the_current_regime(self) -> None:
        page = _page()

        scores = score_breakpoint_fidelity(
            page, page, breakpoint=BreakpointName.DESKTOP
        )

        assert scores.regime_version == CURRENT_REGIME_VERSION

    def test_hook_raises_for_an_unmeasured_breakpoint(self) -> None:
        page = _page()
        hook = score_hook_from_observations(
            {BreakpointName.DESKTOP: page}, {BreakpointName.DESKTOP: page}
        )

        class _Capture:
            breakpoint = BreakpointName.MOBILE

        with pytest.raises(ValueError, match="unmeasured breakpoint"):
            hook(_Capture())

    def test_duplicate_section_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="unique"):
            PageObservation(
                viewport_width=1440, sections=(_section("hero"), _section("hero"))
            )


class TestDeterminism:
    def test_repeated_evaluation_is_identical(self, tmp_path: Path) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        first, first_blockers = evaluate_project_fidelity(tmp_path)
        second, second_blockers = evaluate_project_fidelity(tmp_path)

        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
        assert first_blockers == second_blockers
