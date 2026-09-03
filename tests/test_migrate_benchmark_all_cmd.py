"""CliRunner coverage for the combined multi-corpus offline benchmark command."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.cli import cli

IMAGE_MANIFEST = (
    Path(__file__).parent / "fixtures" / "design-image-benchmarks" / "manifest.json"
)
HTML_MANIFEST = (
    Path(__file__).parent / "fixtures" / "design-benchmarks" / "manifest.json"
)


def test_default_run_covers_both_committed_corpora_and_writes_combined_reports(
    runner, tmp_path
) -> None:
    output = tmp_path / "benchmark-all"

    result = runner.invoke(cli, ["migrate", "benchmark-all", "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert (output / "design-benchmarks" / "benchmark.json").exists()
    assert (output / "design-benchmarks" / "benchmark.md").exists()
    assert (output / "design-image-benchmarks" / "benchmark.json").exists()
    assert (output / "design-image-benchmarks" / "benchmark.md").exists()
    assert (output / "combined.json").exists()
    assert (output / "combined.md").exists()

    combined = json.loads((output / "combined.json").read_text(encoding="utf-8"))
    assert combined["passed"] is True
    assert combined["corpora"] == ["design-benchmarks", "design-image-benchmarks"]
    metric_names = {row["metric"] for row in combined["rows"]}
    assert "template_top1_accuracy" in metric_names
    assert "visitor_content_retention" in metric_names


def test_json_output_lists_per_corpus_pass_fail_and_output_paths(runner, tmp_path) -> None:
    output = tmp_path / "benchmark-all-json"

    result = runner.invoke(
        cli, ["migrate", "benchmark-all", "--output", str(output), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["passed"] is True
    assert payload["combined_json"] == str(output / "combined.json")
    assert payload["combined_md"] == str(output / "combined.md")
    corpora = {entry["corpus"]: entry for entry in payload["corpora"]}
    assert set(corpora) == {"design-benchmarks", "design-image-benchmarks"}
    for entry in corpora.values():
        assert entry["passed"] is True
        assert Path(entry["json_report"]).exists()
        assert Path(entry["human_report"]).exists()


def test_explicit_manifests_run_only_the_supplied_corpora(runner, tmp_path) -> None:
    output = tmp_path / "benchmark-all-explicit"

    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark-all",
            "--output",
            str(output),
            "--manifest",
            str(IMAGE_MANIFEST),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [entry["corpus"] for entry in payload["corpora"]] == ["design-image-benchmarks"]
    assert (output / "design-image-benchmarks" / "benchmark.json").exists()
    assert not (output / "design-benchmarks").exists()


def test_unknown_manifest_path_returns_structured_configuration_error(runner, tmp_path) -> None:
    result = runner.invoke(
        cli,
        [
            "migrate",
            "benchmark-all",
            "--output",
            str(tmp_path / "missing"),
            "--manifest",
            str(tmp_path / "does-not-exist.json"),
            "--json",
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["error"]["category"] in {
        "benchmark_fixture_error",
        "benchmark_configuration_error",
    }
    assert not (tmp_path / "missing" / "combined.json").exists()
