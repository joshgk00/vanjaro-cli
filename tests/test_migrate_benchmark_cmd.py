"""CliRunner coverage for the committed-fixture offline benchmark command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vanjaro_cli.cli import cli
from vanjaro_cli.commands import migrate_benchmark_cmd
from vanjaro_cli.design.benchmark_corpus import (
    load_benchmark_predictions as real_load_benchmark_predictions,
)
from vanjaro_cli.design.metrics import BenchmarkCasePrediction


IMAGE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "design-image-benchmarks" / "manifest.json"
)

# A template_id that cannot appear in any committed fixture's acceptable-templates
# annotation, so the matcher's top-1 selection is unambiguously wrong.
_SENTINEL_WRONG_TEMPLATE_ID = "sentinel/deliberately-wrong-template.json"


def _degrade_top1_selection(
    predictions: dict[str, BenchmarkCasePrediction], case_id: str, count: int
) -> dict[str, BenchmarkCasePrediction]:
    """Return `predictions` with the first `count` top-1 picks in `case_id` forced wrong.

    Operates on real, already-loaded predictions (real adapters, real matcher) so
    only the top-1 template choice for a controlled handful of sections is
    replaced with a sentinel that cannot satisfy any annotation. This isolates the
    committed-fixture regression test from the matcher's actual accuracy, which
    drifts as matching heuristics improve.
    """
    degraded = dict(predictions)
    prediction = degraded[case_id]
    matches = list(prediction.matches)
    for index in range(min(count, len(matches))):
        match = matches[index]
        wrong_candidate = match.selected_candidate.model_copy(
            update={
                "template_id": _SENTINEL_WRONG_TEMPLATE_ID,
                "template_name": "Deliberately Wrong Sentinel Template",
            }
        )
        matches[index] = match.model_copy(update={"selected_candidate": wrong_candidate})
    degraded[case_id] = prediction.model_copy(update={"matches": tuple(matches)})
    return degraded


def _install_degraded_loader(monkeypatch, *, case_id: str, count: int) -> None:
    """Patch the command's `load_benchmark_predictions` boundary to degrade top-1 picks.

    The real loader (adapters, matcher) still runs; only its output is adjusted
    before the real evaluator, thresholds, and report writer see it.
    """

    def loader(manifest_path, case_ids):
        predictions = real_load_benchmark_predictions(manifest_path, case_ids)
        return _degrade_top1_selection(predictions, case_id=case_id, count=count)

    monkeypatch.setattr(migrate_benchmark_cmd, "load_benchmark_predictions", loader)


def test_offline_benchmark_passes_and_writes_both_reports(runner, tmp_path) -> None:
    output = tmp_path / "benchmark"

    result = runner.invoke(cli, ["migrate", "benchmark", "--output", str(output), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["passed"] is True
    assert len(payload["cases"]) == 5
    assert (output / "benchmark.json").exists()
    assert (output / "benchmark.md").exists()


def test_offline_benchmark_supports_case_filter(runner, tmp_path) -> None:
    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--output",
            str(tmp_path / "filtered"),
            "--case",
            "figma-auto-layout-saas",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["cases"] == ["figma-auto-layout-saas"]


def test_offline_benchmark_threshold_failure_is_nonzero_and_reported(
    runner, tmp_path, monkeypatch
) -> None:
    _install_degraded_loader(monkeypatch, case_id="html-bootstrap-agency", count=1)
    output = tmp_path / "strict"

    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--output",
            str(output),
            "--threshold",
            "template_top1_accuracy=0.99",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "failed"
    failure = payload["threshold_failures"][0]
    assert failure["metric"] == "template_top1_accuracy"
    assert failure["minimum"] == pytest.approx(0.99)
    assert failure["actual"] == pytest.approx(24 / 25)

    assert (output / "benchmark.json").exists()
    assert (output / "benchmark.md").exists()
    report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    top1 = report["aggregate"]["matcher"]["template_top1_accuracy"]
    assert top1["numerator"] == 24
    assert top1["denominator"] == 25
    assert top1["value"] == pytest.approx(24 / 25)
    assert any(
        failure["metric"] == "template_top1_accuracy"
        for failure in report["threshold_failures"]
    )
    markdown = (output / "benchmark.md").read_text(encoding="utf-8")
    assert "template_top1_accuracy" in markdown


def test_offline_benchmark_same_threshold_passes_with_real_predictions(
    runner, tmp_path
) -> None:
    """Paired control: the 0.99 top-1 threshold above only fails because the
    degraded prediction is genuinely below it, not because any --threshold
    flag unconditionally trips a failure. Undegraded, real predictions clear
    the identical threshold.
    """
    output = tmp_path / "strict-control"

    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--output",
            str(output),
            "--threshold",
            "template_top1_accuracy=0.99",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["threshold_failures"] == []
    report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    top1 = report["aggregate"]["matcher"]["template_top1_accuracy"]
    assert top1["value"] == pytest.approx(1.0)


def test_offline_benchmark_unknown_case_returns_structured_error(runner, tmp_path) -> None:
    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--output",
            str(tmp_path / "unknown"),
            "--case",
            "does-not-exist",
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["category"] == "benchmark_fixture_error"
    assert "unknown benchmark case" in payload["error"]["message"]


def test_offline_benchmark_missing_manifest_returns_structured_error(runner, tmp_path) -> None:
    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--manifest",
            str(tmp_path / "missing.json"),
            "--output",
            str(tmp_path / "missing"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["category"] == "benchmark_fixture_error"


def test_assisted_image_benchmark_is_hash_bound_and_explicitly_scoped(
    runner, tmp_path
) -> None:
    output = tmp_path / "image-assisted"

    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--manifest",
            str(IMAGE_MANIFEST),
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["cases"] == ["image-assisted-agency"]
    report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    assert report["cases"][0]["source_kind"] == "image"
    fixture = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    assert "does not measure autonomous pixel interpretation" in fixture["corpus"][
        "measurement_scope"
    ]


def test_assisted_image_benchmark_rejects_unbound_reference_bytes(
    runner, tmp_path
) -> None:
    fixture_root = IMAGE_MANIFEST.parent
    manifest = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    original = fixture_root / manifest["cases"][0]["references"][0]["path"]
    copied = tmp_path / "references" / original.name
    copied.parent.mkdir(parents=True)
    copied.write_bytes(original.read_bytes() + b"tampered")
    evidence = fixture_root / manifest["cases"][0]["source"]["path"]
    copied_evidence = tmp_path / "cases" / "image-assisted-agency" / "evidence.json"
    copied_evidence.parent.mkdir(parents=True)
    copied_evidence.write_bytes(evidence.read_bytes())
    second = fixture_root / manifest["cases"][0]["references"][1]["path"]
    copied_second = tmp_path / "references" / second.name
    copied_second.write_bytes(second.read_bytes())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark",
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--output",
            str(tmp_path / "output"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"]["category"] == "benchmark_fixture_error"
    assert "different image bytes" in payload["error"]["message"]
