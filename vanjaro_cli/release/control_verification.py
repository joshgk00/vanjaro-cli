"""Compatibility, tests, secrets, determinism, performance, and control gates."""

from __future__ import annotations

from pathlib import Path
import subprocess

from pydantic import ValidationError

from vanjaro_cli.release.gates import GateLedger as _GateLedger
from vanjaro_cli.release.models import (
    ControlEvidenceReceipt,
    ReleaseContract,
    TestEvidenceReceipt,
    TestPolicy,
)
from vanjaro_cli.release.paths import _verify_reference
from vanjaro_cli.release.test_evidence import (
    TestRunner,
    discover_test_source_files,
    expected_observation,
)
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    canonical_json_bytes,
    canonical_json_sha256,
    load_strict_json,
)
from vanjaro_cli.reliability.compatibility import validate_compatibility_policy
from vanjaro_cli.reliability.performance import (
    PerformanceEvidence,
    evaluate_performance,
)
from vanjaro_cli.reliability.secret_scan import scan_declared_files


def _verify_compatibility(
    contract: ReleaseContract, root: Path, ledger: _GateLedger
) -> None:
    ok, reason, path = _verify_reference(root, contract.compatibility_policy)
    if not ok or path is None:
        ledger.set("compatibility-policy", "failed", reason)
        return
    try:
        report = validate_compatibility_policy(path, repository_root=root)
    except (ArtifactContractError, ValidationError, ValueError):
        ledger.set("compatibility-policy", "failed", "invalid-policy")
        return
    ledger.set(
        "compatibility-policy",
        "passed" if report.status == "passed" else "failed",
        *(report.failures or ("policy-current",)),
        evidence=(contract.compatibility_policy.sha256,),
    )

def _verify_tests(
    contract: ReleaseContract,
    root: Path,
    ledger: _GateLedger,
    *,
    test_runner: TestRunner | None,
) -> tuple[TestEvidenceReceipt | None, TestPolicy | None, bool, bool]:
    if contract.test_evidence is None:
        return None, None, False, True
    receipt_ok, receipt_reason, receipt_path = _verify_reference(
        root, contract.test_evidence.receipt
    )
    policy_ok, policy_reason, policy_path = _verify_reference(
        root, contract.test_evidence.policy
    )
    if not receipt_ok or receipt_path is None or not policy_ok or policy_path is None:
        ledger.set(
            "non-integration-tests",
            "failed",
            *(
                reason
                for reason in (receipt_reason, policy_reason)
                if reason != "artifact-current"
            ),
        )
        return None, None, False, True
    reasons: list[str] = []
    source_records: list[dict[str, str]] = []
    for reference in contract.test_evidence.source_files:
        ref_ok, ref_reason, _ = _verify_reference(root, reference)
        if not ref_ok:
            reasons.append(ref_reason)
        source_records.append({"path": reference.path, "sha256": reference.sha256})
    try:
        receipt = TestEvidenceReceipt.model_validate(load_strict_json(receipt_path))
        policy = TestPolicy.model_validate(load_strict_json(policy_path))
    except (ArtifactContractError, ValidationError):
        ledger.set("non-integration-tests", "failed", "invalid-test-receipt")
        return None, None, False, True
    try:
        discovered_refs = discover_test_source_files(root, policy.source_globs)
        discovered = {item.path for item in discovered_refs}
    except ValueError:
        discovered = None
    declared = {item.path for item in contract.test_evidence.source_files}
    if discovered is None:
        reasons.append("test-source-scope-invalid")
    elif discovered != declared:
        reasons.append("test-source-inventory-mismatch")
    if receipt.command != policy.command:
        reasons.append("test-command-mismatch")
    if receipt.failed or receipt.errors or receipt.passed != receipt.collected:
        reasons.append("test-failure")
    if (
        receipt.allowed_deselected != policy.allowed_deselected
        or receipt.deselected != policy.allowed_deselected
    ):
        reasons.append("unexpected-deselection")
    if receipt.node_ids_sha256 != canonical_json_sha256(sorted(receipt.node_ids)):
        reasons.append("test-node-inventory-mismatch")
    if receipt.source_tree_sha256 != canonical_json_sha256(
        sorted(source_records, key=lambda item: item["path"])
    ):
        reasons.append("test-source-tree-mismatch")
    if reasons:
        ledger.set(
            "non-integration-tests", "failed", *reasons,
            evidence=(
                contract.test_evidence.policy.sha256,
                contract.test_evidence.receipt.sha256,
            ),
        )
        return receipt, policy, False, True
    if test_runner is None:
        ledger.set(
            "non-integration-tests",
            "incomplete",
            "test-rerun-not-authorized",
            evidence=(
                contract.test_evidence.policy.sha256,
                contract.test_evidence.receipt.sha256,
            ),
        )
        return receipt, policy, False, False
    try:
        observed = test_runner(root, policy)
    except (OSError, subprocess.SubprocessError, ValueError):
        reasons.append("test-rerun-failed")
    except Exception:
        reasons.append("test-rerun-failed")
    else:
        if observed != expected_observation(receipt):
            reasons.append("test-receipt-not-reproducible")
    passed = not reasons
    ledger.set(
        "non-integration-tests",
        "passed" if passed else "failed",
        *(reasons or ("complete-test-suite-passed",)),
        evidence=(
            contract.test_evidence.policy.sha256,
            contract.test_evidence.receipt.sha256,
        ),
    )
    return receipt, policy, passed, True


def _verify_secret_scan(
    contract: ReleaseContract, root: Path, ledger: _GateLedger
) -> None:
    if not contract.secret_scan_files:
        return
    report = scan_declared_files(root, contract.secret_scan_files)
    reasons = tuple(item.code for item in report.errors) + tuple(
        item.rule_id for item in report.findings
    )
    ledger.set(
        "secret-scan",
        "passed" if report.status == "passed" else "failed",
        *(reasons or ("declared-artifacts-clean",)),
        evidence=tuple(item.sha256 for item in report.files),
    )


def _verify_determinism(
    contract: ReleaseContract, root: Path, ledger: _GateLedger
) -> None:
    if not contract.deterministic_json_files:
        return
    reasons: list[str] = []
    digests: list[str] = []
    for reference in contract.deterministic_json_files:
        ok, reason, path = _verify_reference(root, reference)
        if not ok or path is None:
            reasons.append(reason)
            continue
        try:
            value = load_strict_json(path)
            if path.read_bytes() != canonical_json_bytes(value):
                reasons.append("noncanonical-json")
        except (OSError, ArtifactContractError):
            reasons.append("invalid-json")
        digests.append(reference.sha256)
    ledger.set(
        "deterministic-artifacts",
        "failed" if reasons else "passed",
        *(reasons or ("canonical-artifacts-current",)),
        evidence=tuple(digests),
    )


def _verify_performance(
    contract: ReleaseContract, root: Path, ledger: _GateLedger
) -> None:
    if contract.performance_evidence is None:
        return
    ok, reason, path = _verify_reference(root, contract.performance_evidence)
    if not ok or path is None:
        ledger.set("performance-budgets", "failed", reason)
        return
    try:
        evidence = PerformanceEvidence.model_validate(load_strict_json(path))
        report = evaluate_performance(evidence)
    except (ArtifactContractError, ValidationError):
        ledger.set("performance-budgets", "failed", "invalid-performance-evidence")
        return
    ledger.set(
        "performance-budgets",
        "passed" if report.status == "passed" else "failed",
        *(report.failures or ("performance-budgets-met",)),
        evidence=(contract.performance_evidence.sha256,),
    )


def _verify_controls(
    contract: ReleaseContract,
    root: Path,
    ledger: _GateLedger,
    *,
    test_receipt: TestEvidenceReceipt | None,
    test_policy: TestPolicy | None,
    tests_passed: bool,
    tests_authorized: bool,
) -> None:
    mapping = {
        "structured-diagnostics": "structured_diagnostics",
        "recovery-tests": "recovery_tests",
        "contract-migrations": "contract_migrations",
        "import-boundaries": "import_boundaries",
    }
    if contract.control_evidence is None:
        return
    ok, reason, path = _verify_reference(root, contract.control_evidence.receipt)
    if not ok or path is None:
        for gate_id in mapping:
            ledger.set(gate_id, "failed", reason)
        return
    try:
        receipt = ControlEvidenceReceipt.model_validate(load_strict_json(path))
    except (ArtifactContractError, ValidationError):
        for gate_id in mapping:
            ledger.set(gate_id, "failed", "invalid-control-receipt")
        return
    if (
        test_receipt is None
        or test_policy is None
        or not tests_passed
        or contract.test_evidence is None
        or receipt.test_receipt_sha256 != contract.test_evidence.receipt.sha256
    ):
        for gate_id in mapping:
            ledger.set(
                gate_id,
                "failed" if tests_authorized else "incomplete",
                (
                    "test-evidence-unverified"
                    if tests_authorized
                    else "test-rerun-not-authorized"
                ),
            )
        return
    verified_node_ids = set(test_receipt.node_ids)
    for gate_id, field in mapping.items():
        result = getattr(receipt, field)
        declared_ids = set(result.evidence_ids)
        required_ids = set(getattr(test_policy.required_controls, field))
        reasons: list[str] = []
        if declared_ids != required_ids:
            reasons.append("control-policy-mismatch")
        if not declared_ids.issubset(verified_node_ids):
            reasons.append("control-test-not-verified")
        ledger.set(
            gate_id,
            "failed" if reasons else "passed",
            *(reasons or ("control-tests-verified",)),
            evidence=(contract.control_evidence.receipt.sha256,),
        )


__all__ = [
    "_verify_compatibility",
    "_verify_controls",
    "_verify_determinism",
    "_verify_performance",
    "_verify_secret_scan",
    "_verify_tests",
]
