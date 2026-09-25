"""Fresh-subprocess regression tests for the benchmark import-order defect.

vanjaro_cli.design.benchmark_corpus imports vanjaro_cli.orchestration.image_acquisition.
Eagerly importing the orchestration package pulls in project_verify ->
project_capture_evidence -> vanjaro_cli.release.paths, which triggers the
release package __init__ to eagerly load verifier -> benchmark_verification.
If benchmark_verification imports vanjaro_cli.design.benchmark_corpus at
module scope, that re-enters benchmark_corpus while it is still mid-import
and raises a partial-initialization ImportError. The fix defers that import
into _run_current_benchmark so importing benchmark_verification (and
anything that imports it) never needs benchmark_corpus to already exist.

Each scenario below runs in an independent, fresh subprocess (normal
sys.executable, explicit repo cwd) so that no prior import in this test
process's own sys.modules cache can hide the ordering bug. Only the
deliberate import(s) named in each script happen before the assertion;
nothing here primes vanjaro_cli.cli or vanjaro_cli.release ahead of the
scenario under test.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "design-benchmarks" / "manifest.json"
DEFAULT_BASELINE = REPO_ROOT / "tests" / "fixtures" / "design-benchmarks" / "baseline-score-report.json"
TIMEOUT_S = 90


def _run_child(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_S,
    )


def _assert_ok(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"child process failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_direct_benchmark_corpus_import_succeeds() -> None:
    result = _run_child(
        "from vanjaro_cli.design.benchmark_corpus import load_benchmark_predictions\n"
        "print('ok:direct-benchmark-corpus')\n"
    )
    _assert_ok(result)
    assert "ok:direct-benchmark-corpus" in result.stdout


def test_release_benchmark_verification_then_benchmark_corpus_succeeds() -> None:
    result = _run_child(
        "import vanjaro_cli.release.benchmark_verification\n"
        "from vanjaro_cli.design.benchmark_corpus import load_benchmark_predictions\n"
        "print('ok:release-then-benchmark-corpus')\n"
    )
    _assert_ok(result)
    assert "ok:release-then-benchmark-corpus" in result.stdout


def test_orchestration_image_acquisition_then_benchmark_corpus_succeeds() -> None:
    result = _run_child(
        "import vanjaro_cli.orchestration.image_acquisition\n"
        "from vanjaro_cli.design.benchmark_corpus import load_benchmark_predictions\n"
        "print('ok:orchestration-then-benchmark-corpus')\n"
    )
    _assert_ok(result)
    assert "ok:orchestration-then-benchmark-corpus" in result.stdout


def test_direct_release_paths_import_succeeds() -> None:
    result = _run_child(
        "import vanjaro_cli.release.paths\n"
        "print('ok:direct-release-paths')\n"
    )
    _assert_ok(result)
    assert "ok:direct-release-paths" in result.stdout


def test_benchmark_corpus_first_load_predictions_for_figma_fixture() -> None:
    code = f"""
from vanjaro_cli.design.benchmark_corpus import DEFAULT_MANIFEST, load_benchmark_predictions

case_id = "figma-auto-layout-saas"
predictions = load_benchmark_predictions(DEFAULT_MANIFEST, (case_id,))
assert set(predictions) == {{case_id}}, predictions
prediction = predictions[case_id]
assert prediction.document is not None
assert len(prediction.matches) > 0
print("ok:figma-document-and-matches")
"""
    result = _run_child(code)
    _assert_ok(result)
    assert "ok:figma-document-and-matches" in result.stdout


def test_run_current_benchmark_with_committed_default_manifest_and_baseline() -> None:
    code = f"""
from pathlib import Path
from vanjaro_cli.release.benchmark_verification import _run_current_benchmark

manifest_path = Path(r"{DEFAULT_MANIFEST}")
baseline_path = Path(r"{DEFAULT_BASELINE}")
case_ids = ("html-bootstrap-agency",)

first = _run_current_benchmark(manifest_path, baseline_path, case_ids)
second = _run_current_benchmark(manifest_path, baseline_path, case_ids)

assert first.corpus_name == "Vanjaro Design Translation Offline Corpus", first.corpus_name
assert first.case_filter == case_ids
assert {{case.case_id for case in first.cases}} == set(case_ids)
assert first == second, "benchmark rerun on the same committed fixtures must reproduce"
print("ok:run-current-benchmark-deferred-path")
"""
    result = _run_child(code)
    _assert_ok(result)
    assert "ok:run-current-benchmark-deferred-path" in result.stdout
