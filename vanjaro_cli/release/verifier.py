"""Portal-safe aggregation and local re-execution of agency release evidence."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from vanjaro_cli.release.benchmark_verification import (
    BenchmarkRunner,
    _run_current_benchmark,
    _verify_benchmark,
)
from vanjaro_cli.release.control_verification import (
    _verify_compatibility,
    _verify_controls,
    _verify_determinism,
    _verify_performance,
    _verify_secret_scan,
    _verify_tests,
)
from vanjaro_cli.release.gates import (
    REQUIRED_GATE_IDS,
    SOURCE_KINDS,
    GateLedger,
    ReleaseVerificationError,
)
from vanjaro_cli.release.models import (
    ReleaseAuditReport,
    ReleaseAuditSummary,
    ReleaseContract,
)
from vanjaro_cli.release.paths import (
    _contains_link_or_reparse,
    _resolve_repository_path,
)
from vanjaro_cli.release.project_verification import (
    TrustedLiveVerifier,
    _verify_project,
    _verify_project_quality,
)
from vanjaro_cli.release.test_evidence import (
    PytestRunObservation,
    TestRunner,
    run_governed_tests,
)
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    canonical_json_sha256,
    load_strict_json,
)

_run_current_tests = run_governed_tests


def verify_release(
    contract_path: Path,
    *,
    repository_root: Path,
    benchmark_runner: BenchmarkRunner | None = None,
    test_runner: TestRunner | None = None,
    execute_tests: bool = False,
    trusted_live_verifier: TrustedLiveVerifier | None = None,
) -> ReleaseAuditReport:
    """Validate a release contract; active checks require explicit authority."""
    if execute_tests and test_runner is not None:
        raise ReleaseVerificationError(
            "execute_tests and test_runner are mutually exclusive authorization inputs"
        )
    authorized_test_runner = _run_current_tests if execute_tests else test_runner

    requested_root = repository_root.expanduser().absolute()
    if _contains_link_or_reparse(requested_root):
        raise ReleaseVerificationError(
            "repository root cannot contain a symlink or reparse point"
        )
    root = requested_root.resolve()
    requested_contract = contract_path.expanduser().absolute()
    if _contains_link_or_reparse(requested_contract):
        raise ReleaseVerificationError("release contract cannot contain a symlink or reparse point")
    resolved_contract = requested_contract.resolve()
    try:
        resolved_contract.relative_to(root)
    except ValueError as exc:
        raise ReleaseVerificationError("release contract must be inside repository root") from exc
    try:
        contract = ReleaseContract.model_validate(load_strict_json(resolved_contract))
    except (ArtifactContractError, ValidationError) as exc:
        raise ReleaseVerificationError(f"invalid release contract: {exc}") from exc
    ledger = GateLedger()
    contract_sha256 = canonical_json_sha256(contract)

    _verify_compatibility(contract, root, ledger)
    for source_kind in SOURCE_KINDS:
        evidence = next(
            (
                item
                for item in contract.benchmarks
                if item.source_kind == source_kind
            ),
            None,
        )
        if evidence is not None:
            _verify_benchmark(
                evidence,
                root=root,
                ledger=ledger,
                benchmark_runner=benchmark_runner or _run_current_benchmark,
            )

    project_quality: list[dict[str, float]] = []
    for source_kind in SOURCE_KINDS:
        evidence = next(
            (
                item
                for item in contract.projects
                if item.source_kind == source_kind
            ),
            None,
        )
        if evidence is not None:
            quality = _verify_project(
                evidence,
                candidate_id=contract.candidate_id,
                evaluation_date=contract.evaluation_date,
                root=root,
                ledger=ledger,
                trusted_live_verifier=trusted_live_verifier,
            )
            if quality is not None:
                project_quality.append(quality)
    _verify_project_quality(project_quality, ledger)
    test_receipt, test_policy, tests_passed, tests_authorized = _verify_tests(
        contract, root, ledger, test_runner=authorized_test_runner
    )
    _verify_secret_scan(contract, root, ledger)
    _verify_determinism(contract, root, ledger)
    _verify_performance(contract, root, ledger)
    _verify_controls(
        contract,
        root,
        ledger,
        test_receipt=test_receipt,
        test_policy=test_policy,
        tests_passed=tests_passed,
        tests_authorized=tests_authorized,
    )

    gates = ledger.report()
    counts = {
        status: sum(item.status == status for item in gates)
        for status in ("passed", "failed", "incomplete")
    }
    overall = (
        "failed"
        if counts["failed"]
        else "incomplete"
        if counts["incomplete"]
        else "passed"
    )
    return ReleaseAuditReport(
        candidate_id=contract.candidate_id,
        contract_sha256=contract_sha256,
        status=overall,
        summary=ReleaseAuditSummary(**counts),
        gates=gates,
    )


__all__ = [
    "PytestRunObservation",
    "REQUIRED_GATE_IDS",
    "ReleaseVerificationError",
    "TrustedLiveVerifier",
    "_resolve_repository_path",
    "_run_current_benchmark",
    "_run_current_tests",
    "verify_release",
]
