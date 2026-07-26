"""CliRunner coverage for the committed-fixture offline benchmark command."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.cli import cli


IMAGE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "design-image-benchmarks" / "manifest.json"
)


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


def test_offline_benchmark_threshold_failure_is_nonzero_and_reported(runner, tmp_path) -> None:
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
    assert payload["threshold_failures"][0]["metric"] == "template_top1_accuracy"
    assert (output / "benchmark.json").exists()


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
