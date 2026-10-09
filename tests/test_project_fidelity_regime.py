"""RT-37 — evidence captured under another scoring regime is never scored."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.test_project_fidelity import (
    _all_breakpoints,
    _manifest,
    _multi_page_document,
    _not_declared,
    _page,
    _record_multi_page,
    _v2_canonical_attempt,
    _write_build_manifests,
    _write_evidence,
    _write_resolved_document,
)
from vanjaro_cli.design.fidelity import CURRENT_REGIME_VERSION
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.orchestration.project_capture_v2 import record_page_capture_v2
from vanjaro_cli.orchestration.project_fidelity import (
    FIDELITY_EVIDENCE_PATH,
    evaluate_project_fidelity,
)

ALL_BREAKPOINTS = (BreakpointName.DESKTOP, BreakpointName.TABLET, BreakpointName.MOBILE)
STALE_REASON = f"re-capture required (regime {CURRENT_REGIME_VERSION})"


def _restamp_regime(root: Path, regime_version: int | None) -> None:
    """Rewrite every per-page record as if an earlier regime (or none) had written it."""

    for record_path in (root / "qa/capture-evidence").glob("*.json"):
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if regime_version is None:
            record.pop("regime_version", None)
        else:
            record["regime_version"] = regime_version
        record_path.write_text(json.dumps(record), encoding="utf-8")


def _record_source_aware_page(root: Path, page_id: str) -> None:
    document = _multi_page_document(page_id)
    _write_resolved_document(root, document)
    _write_build_manifests(root)
    record_page_capture_v2(
        root,
        document,
        _manifest(),
        page_id=page_id,
        built_url=f"https://build.example/{page_id}",
        attempts=tuple(
            _v2_canonical_attempt(root, page_id, breakpoint) for breakpoint in ALL_BREAKPOINTS
        ),
    )


class TestRegimeStamp:
    def test_every_recorder_stamps_the_regime_that_captured_the_evidence(
        self, tmp_path: Path
    ) -> None:
        manifest = _manifest()
        document = _multi_page_document("home", "about")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)
        record_page_capture_v2(
            tmp_path,
            document,
            manifest,
            page_id="about",
            built_url="https://build.example/about",
            attempts=tuple(_not_declared(breakpoint) for breakpoint in ALL_BREAKPOINTS),
        )

        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (tmp_path / "qa/capture-evidence").glob("*.json")
        ]
        legacy = json.loads((tmp_path / FIDELITY_EVIDENCE_PATH).read_text(encoding="utf-8"))

        assert {record["schema_version"] for record in records} == {
            "capture-evidence-v1",
            "capture-evidence-v2",
        }
        assert [record["regime_version"] for record in records] == [CURRENT_REGIME_VERSION] * 2
        assert legacy["regime_version"] == CURRENT_REGIME_VERSION


class TestStaleRegimeEvidence:
    @pytest.mark.parametrize("recorded", [None, CURRENT_REGIME_VERSION - 1, 1])
    def test_legacy_evidence_from_another_regime_is_not_scored(
        self, tmp_path: Path, recorded: int | None
    ) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
            regime_version=recorded,
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "not_scored"
        assert report["reason"] == STALE_REASON
        assert report["recorded_regime_version"] == recorded
        assert report["legacy"] is True
        assert blockers == [f"visual fidelity was not scored: {STALE_REASON}"]

    def test_legacy_evidence_from_the_current_regime_is_still_scored(
        self, tmp_path: Path
    ) -> None:
        page = _page(with_integrity=True)
        _write_evidence(
            tmp_path,
            expected=_all_breakpoints(page),
            observed=_all_breakpoints(page),
        )

        report, blockers = evaluate_project_fidelity(tmp_path)

        assert report["status"] == "scored"
        assert "recorded_regime_version" not in report
        assert blockers == []

    @pytest.mark.parametrize("recorded", [None, CURRENT_REGIME_VERSION - 1])
    def test_a_workspace_page_from_another_regime_blocks_with_one_clear_reason(
        self, tmp_path: Path, recorded: int | None
    ) -> None:
        manifest = _manifest()
        document = _multi_page_document("home")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)
        _restamp_regime(tmp_path, recorded)

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)

        assert report["status"] == "not_scored"
        assert report["passed"] is False
        assert report["pages"]["home"]["reason"] == STALE_REASON
        assert report["pages"]["home"]["recorded_regime_version"] == recorded
        assert blockers == [f"page home: visual fidelity was not scored: {STALE_REASON}"]

    def test_a_source_aware_page_from_another_regime_blocks_too(self, tmp_path: Path) -> None:
        _record_source_aware_page(tmp_path, "home")
        fresh, _ = evaluate_project_fidelity(tmp_path, _manifest())
        assert fresh["pages"]["home"]["status"] == "scored"

        _restamp_regime(tmp_path, CURRENT_REGIME_VERSION - 1)
        report, blockers = evaluate_project_fidelity(tmp_path, _manifest())

        assert report["pages"]["home"]["status"] == "not_scored"
        assert report["pages"]["home"]["reason"] == STALE_REASON
        assert blockers == [f"page home: visual fidelity was not scored: {STALE_REASON}"]

    def test_one_stale_page_keeps_the_workspace_from_passing(self, tmp_path: Path) -> None:
        manifest = _manifest()
        document = _multi_page_document("home", "about")
        _write_resolved_document(tmp_path, document)
        _record_multi_page(tmp_path, document, "home", manifest=manifest)
        _record_multi_page(tmp_path, document, "about", manifest=manifest)
        for path in (tmp_path / "qa/capture-evidence").glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if record["page_id"] == "about":
                del record["regime_version"]
                path.write_text(json.dumps(record), encoding="utf-8")

        report, blockers = evaluate_project_fidelity(tmp_path, manifest)

        assert report["pages"]["home"]["status"] == "scored"
        assert report["pages"]["about"]["status"] == "not_scored"
        assert report["status"] == "partially_scored"
        assert report["passed"] is False
        assert blockers == [f"page about: visual fidelity was not scored: {STALE_REASON}"]
