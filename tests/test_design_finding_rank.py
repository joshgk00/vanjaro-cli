"""Tests for value ranking and `vanjaro fidelity rank` (VF-103)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from vanjaro_cli.cli import cli
from vanjaro_cli.design.fidelity import FidelityDimension
from vanjaro_cli.design.finding_ledger import (
    ClusterKind,
    CorpusLedger,
    LedgerCluster,
    LedgerOccurrence,
)
from vanjaro_cli.design.finding_rank import (
    BREAKPOINT_WEIGHTS,
    rank_ledger,
    render_ranked_queue,
)
from vanjaro_cli.design.models import BreakpointName
from vanjaro_cli.design.reports import (
    FindingCategory,
    PipelineStage,
    ReportSeverity,
)


def _occurrence(
    site_id: str,
    section_id: str,
    breakpoint: BreakpointName = BreakpointName.DESKTOP,
) -> LedgerOccurrence:
    return LedgerOccurrence(
        site_id=site_id, section_id=section_id, breakpoint=breakpoint
    )


def _finding_cluster(
    key: str,
    occurrences: tuple[LedgerOccurrence, ...],
    severity: ReportSeverity = ReportSeverity.MEDIUM,
) -> LedgerCluster:
    return LedgerCluster(
        key=key,
        kind=ClusterKind.FINDING,
        occurrences=occurrences,
        pipeline_stage=PipelineStage.STYLE_TRANSLATION,
        category=FindingCategory.STYLE,
        source_file="vanjaro_cli/design/style_translation.py",
        max_severity=severity,
    )


def _deficit_cluster(
    dimension: FidelityDimension,
    occurrences: tuple[LedgerOccurrence, ...],
    *,
    forces_zero: bool = False,
) -> LedgerCluster:
    return LedgerCluster(
        key=dimension.value,
        kind=ClusterKind.DEFICIT,
        dimension=dimension,
        occurrences=occurrences,
        forces_zero=forces_zero,
    )


def _ledger(*clusters: LedgerCluster, site_ids: tuple[str, ...] = ("alpha",)) -> CorpusLedger:
    return CorpusLedger(regime_version=1, site_ids=site_ids, clusters=clusters)


def _keys(queue) -> list[str]:
    return [cluster.key for cluster in queue.clusters]


def test_a_widespread_defect_outranks_a_worse_local_one() -> None:
    """Twelve sections across five sites beats one section, even a severe one."""

    widespread = _finding_cluster(
        "wide",
        tuple(
            _occurrence(f"site{index}", f"s{section}")
            for index in range(5)
            for section in range(3)
        ),
        severity=ReportSeverity.LOW,
    )
    local = _finding_cluster(
        "local", (_occurrence("alpha", "s1"),), severity=ReportSeverity.HIGH
    )

    queue = rank_ledger(
        _ledger(widespread, local, site_ids=tuple(f"site{i}" for i in range(5)) + ("alpha",))
    )

    assert _keys(queue) == ["wide", "local"]


def test_mobile_outranks_desktop_when_everything_else_matches() -> None:
    desktop = _finding_cluster(
        "desktop-only", (_occurrence("alpha", "s1", BreakpointName.DESKTOP),)
    )
    mobile = _finding_cluster(
        "mobile-only", (_occurrence("alpha", "s1", BreakpointName.MOBILE),)
    )

    queue = rank_ledger(_ledger(desktop, mobile))

    assert _keys(queue) == ["mobile-only", "desktop-only"]
    assert BREAKPOINT_WEIGHTS[BreakpointName.MOBILE] > BREAKPOINT_WEIGHTS[
        BreakpointName.DESKTOP
    ]


def test_the_heaviest_breakpoint_decides_and_desktop_cannot_dilute_mobile() -> None:
    mixed = _finding_cluster(
        "mixed",
        (
            _occurrence("alpha", "s1", BreakpointName.DESKTOP),
            _occurrence("alpha", "s2", BreakpointName.DESKTOP),
            _occurrence("alpha", "s3", BreakpointName.MOBILE),
        ),
    )

    queue = rank_ledger(_ledger(mixed))

    assert queue.clusters[0].breakpoint_weight == BREAKPOINT_WEIGHTS[
        BreakpointName.MOBILE
    ]


def test_severity_raises_value_when_reach_is_equal() -> None:
    low = _finding_cluster("low", (_occurrence("alpha", "s1"),), ReportSeverity.LOW)
    high = _finding_cluster("high", (_occurrence("alpha", "s1"),), ReportSeverity.HIGH)

    queue = rank_ledger(_ledger(low, high))

    assert _keys(queue) == ["high", "low"]


def test_a_forced_zero_deficit_outranks_an_ordinary_one() -> None:
    ordinary = _deficit_cluster(FidelityDimension.COLOR, (_occurrence("alpha", "s1"),))
    invalid = _deficit_cluster(
        FidelityDimension.MEDIA, (_occurrence("alpha", "s1"),), forces_zero=True
    )

    queue = rank_ledger(_ledger(ordinary, invalid))

    assert _keys(queue) == ["media", "color"]


def test_declared_effort_divides_the_value_and_is_reported() -> None:
    cheap = _finding_cluster("cheap", (_occurrence("alpha", "s1"),))
    costly = _finding_cluster(
        "costly", (_occurrence("alpha", "s1"), _occurrence("alpha", "s2"))
    )

    queue = rank_ledger(_ledger(cheap, costly), effort={"costly": 8.0})

    assert _keys(queue) == ["cheap", "costly"]
    by_key = {cluster.key: cluster for cluster in queue.clusters}
    assert by_key["costly"].effort == 8.0
    assert by_key["costly"].effort_is_default is False
    assert by_key["cheap"].effort_is_default is True


def test_an_unusable_effort_falls_back_and_says_so() -> None:
    """Inventing an estimate would order real work by a number nobody measured."""

    queue = rank_ledger(
        _ledger(_finding_cluster("a", (_occurrence("alpha", "s1"),))),
        effort={"a": 0.0},
    )

    assert queue.clusters[0].effort_is_default is True
    assert any("non-positive effort" in warning for warning in queue.warnings)


def test_a_blocked_cluster_sorts_last_and_keeps_its_evidence() -> None:
    big = _finding_cluster(
        "big", tuple(_occurrence("alpha", f"s{i}") for i in range(6))
    )
    small = _finding_cluster("small", (_occurrence("alpha", "s1"),))

    queue = rank_ledger(
        _ledger(big, small), blocked={"big": "revert: corpus mean fell"}
    )

    assert _keys(queue) == ["small", "big"]
    blocked_cluster = queue.clusters[-1]
    assert blocked_cluster.blocked is True
    assert blocked_cluster.blocked_reason == "revert: corpus mean fell"
    assert blocked_cluster.section_count == 6
    assert queue.next_unblocked.key == "small"


def test_an_effort_entry_for_no_cluster_is_reported_not_ignored_silently() -> None:
    queue = rank_ledger(
        _ledger(_finding_cluster("a", (_occurrence("alpha", "s1"),))),
        effort={"ghost": 2.0},
    )

    assert any("no cluster named 'ghost'" in warning for warning in queue.warnings)


def test_ties_break_on_key_so_the_order_never_drifts() -> None:
    first = _finding_cluster("bbb", (_occurrence("alpha", "s1"),))
    second = _finding_cluster("aaa", (_occurrence("alpha", "s1"),))

    assert _keys(rank_ledger(_ledger(first, second))) == ["aaa", "bbb"]
    assert _keys(rank_ledger(_ledger(second, first))) == ["aaa", "bbb"]


def test_the_rendered_queue_marks_an_unestimated_effort() -> None:
    text = render_ranked_queue(
        rank_ledger(_ledger(_finding_cluster("a", (_occurrence("alpha", "s1"),))))
    )

    assert "default, not estimated" in text


def _write_ledger(path: Path) -> None:
    ledger = _ledger(
        _finding_cluster("wide", tuple(_occurrence("alpha", f"s{i}") for i in range(4))),
        _finding_cluster("narrow", (_occurrence("alpha", "s1"),)),
    )
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")


def test_rank_command_emits_json_with_the_queue(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    _write_ledger(ledger_path)

    result = CliRunner().invoke(cli, ["fidelity", "rank", str(ledger_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["next_cluster"] == "wide"
    assert [c["key"] for c in payload["queue"]["clusters"]] == ["wide", "narrow"]


def test_rank_command_regenerates_from_current_evidence(tmp_path: Path) -> None:
    """The queue cannot go stale, because nothing is cached between runs."""

    ledger_path = tmp_path / "ledger.json"
    _write_ledger(ledger_path)
    runner = CliRunner()

    first = runner.invoke(cli, ["fidelity", "rank", str(ledger_path), "--json"])
    assert json.loads(first.output)["next_cluster"] == "wide"

    smaller = _ledger(_finding_cluster("narrow", (_occurrence("alpha", "s1"),)))
    ledger_path.write_text(smaller.model_dump_json(indent=2), encoding="utf-8")

    second = runner.invoke(cli, ["fidelity", "rank", str(ledger_path), "--json"])
    payload = json.loads(second.output)
    assert payload["next_cluster"] == "narrow"
    assert [c["key"] for c in payload["queue"]["clusters"]] == ["narrow"]


def test_rank_command_reports_human_output(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    _write_ledger(ledger_path)

    result = CliRunner().invoke(cli, ["fidelity", "rank", str(ledger_path)])

    assert result.exit_code == 0, result.output
    assert "Ranked work queue" in result.output
    assert "1. wide" in result.output


def test_rank_command_rejects_a_file_that_is_not_a_ledger(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "a ledger"}', encoding="utf-8")

    result = CliRunner().invoke(cli, ["fidelity", "rank", str(bad), "--json"])

    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "error"


def test_rank_command_reports_a_missing_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["fidelity", "rank", str(tmp_path / "gone.json")])

    assert result.exit_code != 0
    assert "not found" in result.output
