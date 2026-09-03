"""Aggregate, fail-closed agency release audit tests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import zlib

import pytest

from vanjaro_cli.commands.release_cmd import release
from vanjaro_cli.design.metrics import BenchmarkReport
from vanjaro_cli.design.models import SourceKind
from vanjaro_cli.project import (
    ProjectSource,
    ProjectStage,
    StageRecord,
    StageStatus,
    create_manifest,
    fingerprint_files,
    initialize_workspace,
    write_manifest,
)
from vanjaro_cli.project.publish_receipt import fingerprint_publish_payload
from vanjaro_cli.release.verifier import (
    REQUIRED_GATE_IDS,
    ReleaseVerificationError,
    PytestRunObservation,
    _run_current_benchmark,
    _run_current_tests,
    _resolve_repository_path,
    verify_release,
)
from vanjaro_cli.reliability import (
    atomic_write_json,
    canonical_json_sha256,
)
from vanjaro_cli.reliability.artifacts import load_strict_json


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha(path)}


def _write(root: Path, relative: str, value: object) -> Path:
    path = root / relative
    atomic_write_json(path, value)
    return path


def _metric() -> dict[str, object]:
    return {"status": "measured", "numerator": 10, "denominator": 10, "value": 1.0}


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _write_png(path: Path, width: int, height: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = b"".join(b"\x00" + b"\x00" * (width * 4) for _ in range(height))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(pixels))
        + _png_chunk(b"IEND", b"")
    )


def _synthetic_benchmark_runner(
    manifest_path: Path, baseline_path: Path, case_ids: tuple[str, ...]
) -> BenchmarkReport:
    del baseline_path, case_ids
    return BenchmarkReport.model_validate(
        load_strict_json(manifest_path.parent / "benchmark.json")
    )


def _synthetic_test_runner(root: Path, policy: object) -> PytestRunObservation:
    del policy
    receipt = load_strict_json(root / "evidence" / "receipts" / "tests.json")
    assert isinstance(receipt, dict)
    return PytestRunObservation(
        collected=receipt["collected"],
        passed=receipt["passed"],
        failed=receipt["failed"],
        errors=receipt["errors"],
        deselected=receipt["deselected"],
        node_ids=tuple(sorted(receipt["node_ids"])),
    )


def _trusted_live_verifier(live: object) -> bool:
    del live
    return True


class _ArbitraryIterable:
    def __iter__(self):
        return iter(())


def test_governed_test_runner_preserves_home_but_strips_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = load_strict_json(ROOT / "release" / "test-policy.json")
    from vanjaro_cli.release.models import TestPolicy

    validated = TestPolicy.model_validate(policy)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("VANJARO_PASSWORD", "portal-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "model-secret")
    monkeypatch.setenv("HTTPS_PROXY", "https://proxy-secret.example")
    calls: list[dict[str, str]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        calls.append(environment)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="tests/test_one.py::test_one\n", stderr=""
            )
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="1 passed in 0.01s\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    observation = _run_current_tests(tmp_path, validated)

    assert observation.passed == observation.collected == 1
    assert calls and all(item.get("USERPROFILE") == str(tmp_path / "home") for item in calls)
    for environment in calls:
        assert "VANJARO_PASSWORD" not in environment
        assert "OPENAI_API_KEY" not in environment
        assert "HTTPS_PROXY" not in environment


def _benchmark(root: Path, source_kind: str) -> dict[str, object]:
    case_id = f"{source_kind}-case"
    base = root / "evidence" / "benchmarks" / source_kind
    source = _write(root, f"evidence/benchmarks/{source_kind}/source.json", {"synthetic": True})
    annotations = _write(root, f"evidence/benchmarks/{source_kind}/annotations.json", {"synthetic": True})
    reference = base / "reference.svg"
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    manifest = _write(
        root,
        f"evidence/benchmarks/{source_kind}/manifest.json",
        {
            "schema_version": "1.0",
            "cases": [
                {
                    "id": case_id,
                    "source_kind": source_kind,
                    "source": {"path": "source.json"},
                    "annotations": "annotations.json",
                    "references": [{"path": "reference.svg"}],
                }
            ],
        },
    )
    baseline = _write(root, f"evidence/benchmarks/{source_kind}/baseline.json", {"schema_version": "1.0"})
    extraction = {
        name: _metric()
        for name in (
            "section_boundary_precision",
            "section_boundary_recall",
            "semantic_role_accuracy",
            "visitor_content_retention",
            "group_field_association_accuracy",
            "asset_association_accuracy",
            "responsive_observation_coverage",
        )
    }
    matcher = {
        name: _metric()
        for name in (
            "template_top1_accuracy",
            "template_top3_accuracy",
            "high_confidence_precision",
        )
    }
    report = _write(
        root,
        f"evidence/benchmarks/{source_kind}/benchmark.json",
        {
            "schema_version": "1.0",
            "corpus_name": "Synthetic release verifier corpus",
            "case_filter": [case_id],
            "aggregate": {"extraction": extraction, "matcher": matcher},
            "cases": [
                {
                    "case_id": case_id,
                    "source_kind": source_kind,
                    "extraction": extraction,
                    "matcher": matcher,
                    "failures": [],
                }
            ],
            "threshold_failures": [],
            "regressions": [],
        },
    )
    return {
        "source_kind": source_kind,
        "measurement_mode": "autonomous",
        "manifest": _ref(root, manifest),
        "baseline": _ref(root, baseline),
        "report": _ref(root, report),
        "inputs": [_ref(root, item) for item in (source, annotations, reference)],
        "case_ids": [case_id],
    }


def _project(root: Path, source_kind: str, portal_id: int) -> dict[str, object]:
    workspace = root / "evidence" / "projects" / source_kind
    manifest = create_manifest(
        name=f"{source_kind} project",
        project_id=f"{source_kind}-project",
        target_profile=f"{source_kind}-profile",
        expected_portal_id=portal_id,
        expected_base_url=f"http://vanjaro.test/{source_kind}",
        sources=[
            ProjectSource(
                id=f"{source_kind}-source",
                kind=SourceKind(source_kind),
                reference=(
                    f"https://source.test/{source_kind}"
                    if source_kind != "image"
                    else "references/design.png"
                ),
                **(
                    {
                        "evidence_reference": "references/design.evidence.json",
                        "page_reference": "home",
                        "breakpoint": "desktop",
                        "viewport": {"width": 1440, "height": 900},
                    }
                    if source_kind == "image"
                    else {}
                ),
            )
        ],
        agency_pack_name="agency",
        agency_pack_version="1.0.0",
        clock=lambda: NOW,
    )
    initialize_workspace(workspace, manifest)
    stages = dict(manifest.stages)
    for stage in ProjectStage:
        if stage == ProjectStage.INTAKE:
            continue
        if stage in {ProjectStage.VERIFY, ProjectStage.PUBLISH, ProjectStage.LAUNCH}:
            relative = Path("qa") / f"{stage.value}.json"
            _write(root, (workspace / relative).relative_to(root).as_posix(), {"stage": stage.value})
            fingerprint = fingerprint_files(workspace, (relative,))
            stages[stage] = StageRecord(
                stage=stage,
                status=StageStatus.COMPLETED,
                attempt=1,
                input_fingerprint="a" * 64,
                output_fingerprint=fingerprint,
                started_at=NOW,
                completed_at=NOW,
                artifacts=[relative.as_posix()],
            )
        else:
            stages[stage] = StageRecord(
                stage=stage,
                status=StageStatus.SKIPPED,
                completed_at=NOW,
                message="not required by synthetic release fixture",
            )
    manifest = manifest.model_copy(update={"stages": stages})
    write_manifest(workspace, manifest)

    scorecard = {"schema_version": "1.0", "status": "publish_ready"}
    scorecard["fingerprint"] = fingerprint_publish_payload(scorecard)
    scorecard_path = _write(
        root,
        (workspace / "qa" / "maintenance-scorecard.json").relative_to(root).as_posix(),
        scorecard,
    )
    manifest_path = workspace / "project.json"
    manifest_sha = _sha(manifest_path)
    quality_evidence = _write(
        root,
        f"evidence/receipts/quality-{source_kind}.json",
        {
            "schema_version": "project-quality-evidence-v1",
            "candidate_id": "synthetic-complete",
            "project_id": manifest.project.id,
            "source_kind": source_kind,
            "quality": {
                name: {"numerator": 10, "denominator": 10}
                for name in (
                    "eligible_section_editable_coverage",
                    "native_agency_component_ratio",
                    "body_without_generic_fallback",
                    "desktop_tablet_mobile_evidence",
                )
            },
        },
    )
    protocol = _write(
        root,
        f"evidence/policies/effort-protocol-{source_kind}.json",
        {"schema_version": "agency-effort-protocol-v1", "task": "same-site-build"},
    )
    quality_policy = _write(
        root,
        f"evidence/policies/quality-policy-{source_kind}.json",
        {"schema_version": "agency-quality-policy-v1", "thresholds": "release"},
    )
    effort_evidence = _write(
        root,
        f"evidence/receipts/effort-{source_kind}.json",
        {
            "schema_version": "project-effort-evidence-v1",
            "candidate_id": "synthetic-complete",
            "project_id": manifest.project.id,
            "source_kind": source_kind,
            "measurement_protocol": _ref(root, protocol),
            "quality_policy": _ref(root, quality_policy),
            "baseline_sessions": [
                {
                    "session_id": f"{source_kind}-baseline",
                    "operator_id": "operator-1",
                    "minutes": 100,
                }
            ],
            "current_sessions": [
                {
                    "session_id": f"{source_kind}-current",
                    "operator_id": "operator-1",
                    "minutes": 40,
                }
            ],
        },
    )
    project_receipt = _write(
        root,
        f"evidence/receipts/project-{source_kind}.json",
        {
            "schema_version": "project-release-evidence-v1",
            "candidate_id": "synthetic-complete",
            "project_id": manifest.project.id,
            "source_kind": source_kind,
            "project_manifest_sha256": manifest_sha,
            "maintenance_scorecard_sha256": _sha(scorecard_path),
            "quality_evidence_sha256": _sha(quality_evidence),
            "effort_evidence_sha256": _sha(effort_evidence),
        },
    )
    captures: dict[str, object] = {}
    sizes = {"desktop": (1440, 900), "tablet": (768, 1024), "mobile": (390, 844)}
    for breakpoint, (width, height) in sizes.items():
        capture = root / "evidence" / "captures" / f"{source_kind}-{breakpoint}.png"
        _write_png(capture, width, height)
        captures[breakpoint] = {
            "width": width,
            "height": height,
            "artifact": _ref(root, capture),
        }
    portal = {
        "portal_id": portal_id,
        "base_url": f"http://vanjaro.test/{source_kind}",
        "dnn_version": "9.13.7",
        "vanjaro_version": "1.6.0",
        "vanjaro_ai_version": "0.1.0",
    }
    attestation = _write(
        root,
        f"evidence/receipts/live-attestation-{source_kind}.json",
        {
            "schema_version": "agency-live-attestation-v1",
            "candidate_id": "synthetic-complete",
            "project_id": manifest.project.id,
            "source_kind": source_kind,
            "operator_id": "operator-1",
            "observed_at": NOW,
            "portal": portal,
            "capture_sha256": {
                name: capture["artifact"]["sha256"]
                for name, capture in captures.items()
            },
            "capture_routes": {name: "/home" for name in captures},
            "smoke_routes": {
                "editor": "/home/edit",
                "navigation": "/home",
                "public-route": "/home",
                "search": "/search",
            },
            "statement": "I observed this candidate on the stated Vanjaro portal and recorded the linked captures and smoke checks.",
        },
    )
    live_receipt = _write(
        root,
        f"evidence/receipts/live-{source_kind}.json",
        {
            "schema_version": "agency-live-evidence-v1",
            "provenance": "real-vanjaro-portal",
            "candidate_id": "synthetic-complete",
            "project_id": manifest.project.id,
            "source_kind": source_kind,
            "portal": portal,
            "project_manifest_sha256": manifest_sha,
            "publish_fingerprint": stages[ProjectStage.PUBLISH].output_fingerprint,
            "launch_fingerprint": stages[ProjectStage.LAUNCH].output_fingerprint,
            "observed_at": NOW,
            "valid_through": "2026-08-30",
            "captures": captures,
            "smoke_checks": [
                {"check_id": item, "status": "passed"}
                for item in ("editor", "navigation", "public-route", "search")
            ],
            "cleanup_restored": True,
            "attestation": _ref(root, attestation),
        },
    )
    return {
        "source_kind": source_kind,
        "workspace": workspace.relative_to(root).as_posix(),
        "receipt": _ref(root, project_receipt),
        "quality_evidence": _ref(root, quality_evidence),
        "effort_evidence": _ref(root, effort_evidence),
        "live_receipt": _ref(root, live_receipt),
    }


def _complete_contract(root: Path) -> Path:
    (root / "release").mkdir(parents=True)
    shutil.copy2(ROOT / "release" / "compatibility-policy.json", root / "release" / "compatibility-policy.json")
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "0.1.0"\nrequires-python = ">=3.10"\n', encoding="utf-8"
    )
    policy = root / "release" / "compatibility-policy.json"
    source_file = root / "evidence" / "source-tree.txt"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("synthetic source identity\n", encoding="utf-8")
    source_records = [_ref(root, source_file)]
    control_ids = {
        "structured_diagnostics": ("tests/test_controls.py::test_structured_diagnostics",),
        "recovery_tests": ("tests/test_controls.py::test_recovery",),
        "contract_migrations": ("tests/test_controls.py::test_migrations",),
        "import_boundaries": ("tests/test_controls.py::test_import_boundaries",),
    }
    node_ids = tuple(sorted(item for values in control_ids.values() for item in values))
    test_policy = _write(
        root,
        "release/test-policy.json",
        {
            "schema_version": "agency-test-policy-v1",
            "command": "python -m pytest -m not integration -q",
            "allowed_deselected": 1,
            "source_globs": ["evidence/source-tree.txt"],
            "required_controls": control_ids,
        },
    )
    test_receipt = _write(
        root,
        "evidence/receipts/tests.json",
        {
            "schema_version": "test-evidence-v1",
            "command": "python -m pytest -m not integration -q",
            "collected": len(node_ids),
            "passed": len(node_ids),
            "failed": 0,
            "errors": 0,
            "deselected": 1,
            "allowed_deselected": 1,
            "node_ids": node_ids,
            "node_ids_sha256": canonical_json_sha256(sorted(node_ids)),
            "source_tree_sha256": canonical_json_sha256(source_records),
        },
    )
    performance = _write(
        root,
        "evidence/receipts/performance.json",
        {
            "schema_version": "performance-evidence-v1",
            "policy_version": "agency-performance-v1",
            "environment": {
                "python_version": "3.11",
                "implementation": "CPython",
                "operating_system": "Windows",
                "architecture": "AMD64",
                "corpus_sha256": "f" * 64,
            },
            "warmups": 1,
            "cases": {"benchmark": {"samples_ms": [10, 11, 12, 13, 14]}},
            "budgets": {
                "benchmark": {
                    "max_median_ms": 20,
                    "max_p95_ms": 20,
                    "baseline_p95_ms": 15,
                    "max_regression_ratio": 1.2,
                }
            },
        },
    )
    controls = _write(
        root,
        "evidence/receipts/controls.json",
        {
            "schema_version": "reliability-control-evidence-v1",
            "test_receipt_sha256": _sha(test_receipt),
            **{
                name: {"evidence_ids": ids}
                for name, ids in control_ids.items()
            },
        },
    )
    contract = {
        "schema_version": "1.0",
        "candidate_id": "synthetic-complete",
        "evaluation_date": "2026-08-30",
        "compatibility_policy": _ref(root, policy),
        "benchmarks": [_benchmark(root, kind) for kind in ("live_html", "figma", "image")],
        "projects": [_project(root, kind, index + 1) for index, kind in enumerate(("live_html", "figma", "image"))],
        "test_evidence": {
            "policy": _ref(root, test_policy),
            "receipt": _ref(root, test_receipt),
            "source_files": source_records,
        },
        "performance_evidence": _ref(root, performance),
        "control_evidence": {"receipt": _ref(root, controls)},
        "secret_scan_files": ["release/compatibility-policy.json"],
        "deterministic_json_files": [_ref(root, policy)],
    }
    return _write(root, "release/contract.json", contract)


def test_complete_synthetic_release_passes_every_closed_gate(tmp_path: Path) -> None:
    contract = _complete_contract(tmp_path)
    report = verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
        trusted_live_verifier=_trusted_live_verifier,
    )
    assert report.status == "passed"
    assert report.summary.passed == len(REQUIRED_GATE_IDS)
    assert report.summary.failed == report.summary.incomplete == 0
    assert {item.gate_id for item in report.gates} == set(REQUIRED_GATE_IDS)
    canonical_dump = report.model_dump(mode="json")
    assert canonical_dump["summary"] == {
        "passed": len(REQUIRED_GATE_IDS), "failed": 0, "incomplete": 0,
    }
    assert [gate["gate_id"] for gate in canonical_dump["gates"]] == sorted(
        REQUIRED_GATE_IDS
    )
    assert all(gate["status"] == "passed" for gate in canonical_dump["gates"])
    assert canonical_json_sha256(report) == (
        "4bdef765d2fd87312e0a2ad8d09e6ab941c04b64989b89e20fcfa56268f51029"
    )


def test_release_verify_requires_explicit_test_execution(tmp_path: Path) -> None:
    contract = _complete_contract(tmp_path)

    report = verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        trusted_live_verifier=_trusted_live_verifier,
    )
    gates = {item.gate_id: item for item in report.gates}

    assert gates["non-integration-tests"].status == "incomplete"
    assert gates["non-integration-tests"].reason_codes == (
        "test-rerun-not-authorized",
    )
    for gate_id in (
        "structured-diagnostics",
        "recovery-tests",
        "contract-migrations",
        "import-boundaries",
    ):
        assert gates[gate_id].status == "incomplete"
        assert gates[gate_id].reason_codes == ("test-rerun-not-authorized",)


def test_live_gate_requires_trusted_verifier(tmp_path: Path) -> None:
    contract = _complete_contract(tmp_path)

    report = verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gates = {item.gate_id: item for item in report.gates}

    for source_kind in ("live_html", "figma", "image"):
        gate = gates[f"live-smoke-{source_kind}"]
        assert gate.status == "incomplete"
        assert gate.reason_codes == ("trusted-live-verification-required",)


@pytest.mark.parametrize(
    "invalid_result",
    (
        None,
        [],
        {},
        set(),
        iter(()),
        ["failure"],
        {"failure": True},
        {"failure"},
        iter(("failure",)),
        _ArbitraryIterable(),
    ),
    ids=(
        "none", "empty-list", "empty-dict", "empty-set", "empty-generator",
        "list", "mapping", "set", "generator", "arbitrary-iterable",
    ),
)
def test_live_gate_rejects_unsupported_trusted_verifier_results(
    tmp_path: Path, invalid_result: object
) -> None:
    contract = _complete_contract(tmp_path)

    report = verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
        trusted_live_verifier=lambda _live: invalid_result,  # type: ignore[return-value]
    )
    gates = {item.gate_id: item for item in report.gates}

    for source_kind in ("live_html", "figma", "image"):
        gate = gates[f"live-smoke-{source_kind}"]
        assert gate.status == "failed"
        assert gate.reason_codes == ("trusted-live-verifier-invalid-result",)


def test_explicit_test_execution_uses_compatibility_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vanjaro_cli.release.verifier as verifier_module

    contract = _complete_contract(tmp_path)
    calls: list[Path] = []

    def replacement(root: Path, policy: object) -> PytestRunObservation:
        calls.append(root)
        return _synthetic_test_runner(root, policy)

    monkeypatch.setattr(verifier_module, "_run_current_tests", replacement)
    report = verifier_module.verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        execute_tests=True,
        trusted_live_verifier=_trusted_live_verifier,
    )

    assert report.status == "passed"
    assert calls == [tmp_path]


def test_explicit_test_execution_refuses_a_second_runner(tmp_path: Path) -> None:
    contract = _complete_contract(tmp_path)

    with pytest.raises(ReleaseVerificationError, match="mutually exclusive"):
        verify_release(
            contract,
            repository_root=tmp_path,
            test_runner=_synthetic_test_runner,
            execute_tests=True,
        )


def test_unapproved_test_execution_never_calls_compatibility_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vanjaro_cli.release.verifier as verifier_module

    contract = _complete_contract(tmp_path)

    def forbidden(*_args: object) -> PytestRunObservation:
        pytest.fail("compatibility runner executed without authorization")

    monkeypatch.setattr(verifier_module, "_run_current_tests", forbidden)
    report = verifier_module.verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        trusted_live_verifier=_trusted_live_verifier,
    )
    gates = {item.gate_id: item for item in report.gates}

    assert gates["non-integration-tests"].status == "incomplete"
    assert gates["non-integration-tests"].reason_codes == (
        "test-rerun-not-authorized",
    )


def test_modified_evidence_and_assisted_image_fail_closed(tmp_path: Path) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = __import__("json").loads(contract_path.read_text(encoding="utf-8"))
    image = next(item for item in contract["benchmarks"] if item["source_kind"] == "image")
    image["measurement_mode"] = "assisted"
    report_path = tmp_path / image["report"]["path"]
    report_path.write_text(report_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    atomic_write_json(contract_path, contract)

    report = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gates = {item.gate_id: item for item in report.gates}

    assert report.status == "failed"
    assert gates["benchmark-provenance-image"].status == "failed"
    assert "artifact-digest-mismatch" in gates["benchmark-provenance-image"].reason_codes


def test_tracked_contract_reports_known_missing_evidence_without_network_calls(runner) -> None:
    contract = ROOT / "release" / "agency-release-contract.json"
    result = runner.invoke(
        release,
        ["verify", str(contract), "--repository-root", str(ROOT), "--json"],
    )

    assert result.exit_code == 1
    payload = __import__("json").loads(result.output)
    assert payload["status"] == "incomplete"
    assert payload["summary"]["passed"] == 3
    assert payload["summary"]["incomplete"] > 0


def test_reordered_contract_keys_produce_identical_audit_bytes(tmp_path: Path) -> None:
    contract = _complete_contract(tmp_path)
    first = verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    payload = __import__("json").loads(contract.read_text(encoding="utf-8"))
    contract.write_text(__import__("json").dumps(dict(reversed(list(payload.items())))), encoding="utf-8")
    second = verify_release(
        contract,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )

    assert first == second


def test_malformed_benchmark_shape_fails_a_gate_without_traceback(tmp_path: Path) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    benchmark = contract["benchmarks"][0]
    report_path = tmp_path / benchmark["report"]["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["case_filter"] = "not-a-case-list"
    atomic_write_json(report_path, report)
    benchmark["report"] = _ref(tmp_path, report_path)
    atomic_write_json(contract_path, contract)

    audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gate = next(
        item
        for item in audit.gates
        if item.gate_id == "benchmark-provenance-live_html"
    )

    assert gate.status == "failed"
    assert gate.reason_codes == ("invalid-benchmark-json",)


def test_supplied_benchmark_report_must_equal_the_current_code_rerun(
    tmp_path: Path,
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    rerun_reports = {
        item["source_kind"]: BenchmarkReport.model_validate(
            load_strict_json(tmp_path / item["report"]["path"])
        )
        for item in contract["benchmarks"]
    }
    benchmark = contract["benchmarks"][0]
    report_path = tmp_path / benchmark["report"]["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["corpus_name"] = "forged but structurally valid report"
    atomic_write_json(report_path, report)
    benchmark["report"] = _ref(tmp_path, report_path)
    atomic_write_json(contract_path, contract)

    def current_code_runner(
        manifest_path: Path, baseline_path: Path, case_ids: tuple[str, ...]
    ) -> BenchmarkReport:
        del baseline_path, case_ids
        return rerun_reports[manifest_path.parent.name]

    audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=current_code_runner,
        test_runner=_synthetic_test_runner,
    )
    gate = next(
        item
        for item in audit.gates
        if item.gate_id == "benchmark-provenance-live_html"
    )

    assert gate.status == "failed"
    assert "benchmark-report-not-reproducible" in gate.reason_codes


def test_default_benchmark_runner_rebuilds_a_real_committed_case(
    tmp_path: Path,
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    corpus = tmp_path / "evidence" / "real-corpus"
    shutil.copytree(ROOT / "tests" / "fixtures" / "design-benchmarks", corpus)
    manifest_path = corpus / "manifest.json"
    baseline_path = corpus / "baseline-score-report.json"
    case_id = "html-bootstrap-agency"
    report_model = _run_current_benchmark(
        manifest_path, baseline_path, (case_id,)
    )
    report_path = corpus / "release-report.json"
    atomic_write_json(report_path, report_model)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    case = next(item for item in manifest["cases"] if item["id"] == case_id)
    input_paths = [
        corpus / case["source"]["path"],
        corpus / case["annotations"],
        *(corpus / item["path"] for item in case["references"]),
    ]
    real_evidence = {
        "source_kind": "live_html",
        "measurement_mode": "autonomous",
        "manifest": _ref(tmp_path, manifest_path),
        "baseline": _ref(tmp_path, baseline_path),
        "report": _ref(tmp_path, report_path),
        "inputs": [_ref(tmp_path, path) for path in input_paths],
        "case_ids": [case_id],
    }
    contract["benchmarks"] = [
        real_evidence
        if item["source_kind"] == "live_html"
        else item
        for item in contract["benchmarks"]
    ]
    atomic_write_json(contract_path, contract)

    current = verify_release(
        contract_path,
        repository_root=tmp_path,
        test_runner=_synthetic_test_runner,
    )
    current_gate = next(
        item
        for item in current.gates
        if item.gate_id == "benchmark-provenance-live_html"
    )
    assert current_gate.status == "passed"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["corpus_name"] = "forged after the real run"
    atomic_write_json(report_path, report)
    real_evidence["report"] = _ref(tmp_path, report_path)
    atomic_write_json(contract_path, contract)
    forged = verify_release(
        contract_path,
        repository_root=tmp_path,
        test_runner=_synthetic_test_runner,
    )
    forged_gate = next(
        item
        for item in forged.gates
        if item.gate_id == "benchmark-provenance-live_html"
    )
    assert forged_gate.status == "failed"
    assert "benchmark-report-not-reproducible" in forged_gate.reason_codes


def test_raw_project_quality_and_effort_are_bound_and_recomputed(
    tmp_path: Path,
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    project = contract["projects"][0]
    quality_path = tmp_path / project["quality_evidence"]["path"]
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["quality"]["eligible_section_editable_coverage"] = {
        "numerator": 1,
        "denominator": 10,
    }
    atomic_write_json(quality_path, quality)
    project["quality_evidence"] = _ref(tmp_path, quality_path)
    atomic_write_json(contract_path, contract)

    stale = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    stale_gate = next(
        item for item in stale.gates if item.gate_id == "project-ready-live_html"
    )
    assert "quality-evidence-mismatch" in stale_gate.reason_codes

    receipt_path = tmp_path / project["receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["quality_evidence_sha256"] = project["quality_evidence"]["sha256"]
    effort_path = tmp_path / project["effort_evidence"]["path"]
    effort = json.loads(effort_path.read_text(encoding="utf-8"))
    effort["current_sessions"][0]["minutes"] = 90
    atomic_write_json(effort_path, effort)
    project["effort_evidence"] = _ref(tmp_path, effort_path)
    receipt["effort_evidence_sha256"] = project["effort_evidence"]["sha256"]
    atomic_write_json(receipt_path, receipt)
    project["receipt"] = _ref(tmp_path, receipt_path)
    atomic_write_json(contract_path, contract)

    bound = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gates = {item.gate_id: item for item in bound.gates}
    assert gates["project-ready-live_html"].status == "passed"
    assert gates["quality-eligible_section_editable_coverage"].status == "failed"
    assert gates["effort-reduction-live_html"].status == "failed"


def test_self_consistent_fake_capture_and_stale_launch_fingerprint_fail(
    tmp_path: Path,
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    project = contract["projects"][0]
    live_path = tmp_path / project["live_receipt"]["path"]
    live = json.loads(live_path.read_text(encoding="utf-8"))
    capture_path = tmp_path / live["captures"]["desktop"]["artifact"]["path"]
    capture_path.write_bytes(b"not really a PNG")
    live["captures"]["desktop"]["artifact"] = _ref(tmp_path, capture_path)
    live["launch_fingerprint"] = "f" * 64
    attestation_path = tmp_path / live["attestation"]["path"]
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["capture_sha256"]["desktop"] = live["captures"]["desktop"]["artifact"]["sha256"]
    atomic_write_json(attestation_path, attestation)
    live["attestation"] = _ref(tmp_path, attestation_path)
    atomic_write_json(live_path, live)
    project["live_receipt"] = _ref(tmp_path, live_path)
    atomic_write_json(contract_path, contract)

    audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gate = next(item for item in audit.gates if item.gate_id == "live-smoke-live_html")

    assert gate.status == "failed"
    assert "capture-desktop-invalid-png" in gate.reason_codes
    assert "live-launch-fingerprint-mismatch" in gate.reason_codes


def test_control_receipt_cannot_name_tests_outside_verified_policy(
    tmp_path: Path,
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    controls_path = tmp_path / contract["control_evidence"]["receipt"]["path"]
    controls = json.loads(controls_path.read_text(encoding="utf-8"))
    controls["structured_diagnostics"]["evidence_ids"] = [
        "tests/test_fake.py::test_claimed_pass"
    ]
    atomic_write_json(controls_path, controls)
    contract["control_evidence"]["receipt"] = _ref(tmp_path, controls_path)
    atomic_write_json(contract_path, contract)

    audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gates = {item.gate_id: item for item in audit.gates}

    assert gates["non-integration-tests"].status == "passed"
    assert gates["structured-diagnostics"].status == "failed"
    assert "control-policy-mismatch" in gates["structured-diagnostics"].reason_codes
    assert "control-test-not-verified" in gates["structured-diagnostics"].reason_codes


def test_test_receipt_must_match_a_fresh_governed_pytest_run(tmp_path: Path) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / contract["test_evidence"]["receipt"]["path"]
    original = _synthetic_test_runner(tmp_path, object())
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["node_ids"][0] = "tests/test_fake.py::test_claimed_pass"
    receipt["node_ids_sha256"] = canonical_json_sha256(sorted(receipt["node_ids"]))
    atomic_write_json(receipt_path, receipt)
    contract["test_evidence"]["receipt"] = _ref(tmp_path, receipt_path)
    controls_path = tmp_path / contract["control_evidence"]["receipt"]["path"]
    controls = json.loads(controls_path.read_text(encoding="utf-8"))
    controls["test_receipt_sha256"] = contract["test_evidence"]["receipt"]["sha256"]
    atomic_write_json(controls_path, controls)
    contract["control_evidence"]["receipt"] = _ref(tmp_path, controls_path)
    atomic_write_json(contract_path, contract)

    def current_test_runner(root: Path, policy: object) -> PytestRunObservation:
        del root, policy
        return original

    audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=current_test_runner,
    )
    gate = next(item for item in audit.gates if item.gate_id == "non-integration-tests")

    assert gate.status == "failed"
    assert "test-receipt-not-reproducible" in gate.reason_codes


def test_release_evidence_rejects_file_directory_and_workspace_symlinks(
    tmp_path: Path,
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    try:
        policy_link = tmp_path / "release" / "policy-link.json"
        policy_link.symlink_to(tmp_path / "release" / "compatibility-policy.json")
        directory_link = tmp_path / "release-link"
        directory_link.symlink_to(tmp_path / "release", target_is_directory=True)
        project_link = tmp_path / "evidence" / "project-link"
        project_link.symlink_to(
            tmp_path / contract["projects"][0]["workspace"],
            target_is_directory=True,
        )
        contract_link = tmp_path / "release" / "contract-link.json"
        contract_link.symlink_to(contract_path)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(ReleaseVerificationError, match="release contract cannot"):
        verify_release(contract_link, repository_root=tmp_path)

    contract["compatibility_policy"] = _ref(tmp_path, policy_link)
    contract["projects"][0]["workspace"] = project_link.relative_to(tmp_path).as_posix()
    atomic_write_json(contract_path, contract)
    audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    gates = {item.gate_id: item for item in audit.gates}
    assert gates["compatibility-policy"].reason_codes == ("symlink",)
    assert gates["project-ready-live_html"].reason_codes == ("workspace-unavailable",)

    contract["compatibility_policy"] = {
        "path": "release-link/compatibility-policy.json",
        "sha256": _sha(tmp_path / "release" / "compatibility-policy.json"),
    }
    atomic_write_json(contract_path, contract)
    linked_directory_audit = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
    )
    directory_gate = next(
        item
        for item in linked_directory_audit.gates
        if item.gate_id == "compatibility-policy"
    )
    assert directory_gate.reason_codes == ("symlink",)

    root_link = tmp_path.parent / f"{tmp_path.name}-repository-link"
    try:
        root_link.symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"workspace symlink creation is unavailable: {exc}")
    try:
        with pytest.raises(ReleaseVerificationError, match="symlink or reparse"):
            verify_release(contract_path, repository_root=root_link)
    finally:
        root_link.unlink(missing_ok=True)


def test_workspace_internal_paths_reject_links_and_escapes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    qa = workspace / "qa"
    qa.mkdir(parents=True)
    project = workspace / "project.json"
    scorecard = qa / "maintenance-scorecard.json"
    artifact = qa / "stage.json"
    project.write_text("{}", encoding="utf-8")
    scorecard.write_text("{}", encoding="utf-8")
    artifact.write_text("{}", encoding="utf-8")
    artifact_directory = qa / "stage-directory"
    artifact_directory.mkdir()
    link_target = tmp_path / "link-target.json"
    link_target.write_text("{}", encoding="utf-8")
    try:
        project.unlink()
        project.symlink_to(link_target)
        scorecard.unlink()
        scorecard.symlink_to(link_target)
        artifact.unlink()
        artifact.symlink_to(link_target)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    assert _resolve_repository_path(
        tmp_path, "workspace/project.json", expected_type="file"
    ) is None
    assert _resolve_repository_path(
        tmp_path,
        "workspace/qa/maintenance-scorecard.json",
        expected_type="file",
    ) is None
    assert _resolve_repository_path(
        tmp_path, "workspace/qa/stage.json", expected_type="file"
    ) is None
    assert _resolve_repository_path(
        tmp_path, "workspace/qa/stage-directory", expected_type="file"
    ) is None
    assert _resolve_repository_path(
        tmp_path, str(link_target.resolve()), expected_type="file"
    ) is None
    assert _resolve_repository_path(
        tmp_path, "workspace/qa/../project.json", expected_type="file"
    ) is None


@pytest.mark.parametrize(
    ("current_minutes", "expected_status"),
    ((40.0, "passed"), (40.0000001, "failed")),
)
def test_effort_reduction_threshold_is_exact(
    tmp_path: Path, current_minutes: float, expected_status: str
) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    project = contract["projects"][0]
    effort_path = tmp_path / project["effort_evidence"]["path"]
    effort = json.loads(effort_path.read_text(encoding="utf-8"))
    effort["current_sessions"][0]["minutes"] = current_minutes
    atomic_write_json(effort_path, effort)
    project["effort_evidence"] = _ref(tmp_path, effort_path)
    receipt_path = tmp_path / project["receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["effort_evidence_sha256"] = project["effort_evidence"]["sha256"]
    atomic_write_json(receipt_path, receipt)
    project["receipt"] = _ref(tmp_path, receipt_path)
    atomic_write_json(contract_path, contract)

    report = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
        trusted_live_verifier=_trusted_live_verifier,
    )
    gate = next(
        item for item in report.gates
        if item.gate_id == "effort-reduction-live_html"
    )
    assert gate.status == expected_status


def test_effort_aggregate_overflow_fails_closed(tmp_path: Path) -> None:
    contract_path = _complete_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    project = contract["projects"][0]
    effort_path = tmp_path / project["effort_evidence"]["path"]
    effort = json.loads(effort_path.read_text(encoding="utf-8"))
    effort["baseline_sessions"] = [
        {"session_id": "overflow-a", "operator_id": "operator-1", "minutes": 1e308},
        {"session_id": "overflow-b", "operator_id": "operator-1", "minutes": 1e308},
    ]
    atomic_write_json(effort_path, effort)
    project["effort_evidence"] = _ref(tmp_path, effort_path)
    receipt_path = tmp_path / project["receipt"]["path"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["effort_evidence_sha256"] = project["effort_evidence"]["sha256"]
    atomic_write_json(receipt_path, receipt)
    project["receipt"] = _ref(tmp_path, receipt_path)
    atomic_write_json(contract_path, contract)

    report = verify_release(
        contract_path,
        repository_root=tmp_path,
        benchmark_runner=_synthetic_benchmark_runner,
        test_runner=_synthetic_test_runner,
        trusted_live_verifier=_trusted_live_verifier,
    )
    gate = next(
        item for item in report.gates
        if item.gate_id == "effort-reduction-live_html"
    )
    assert gate.status == "failed"
    assert "effort-aggregate-non-finite" in gate.reason_codes
