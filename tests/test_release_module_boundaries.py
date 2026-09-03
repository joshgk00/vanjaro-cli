"""Structural and compatibility boundaries for release verification modules."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from vanjaro_cli.release import (
    REQUIRED_GATE_IDS,
    PytestRunObservation,
    ReleaseVerificationError,
    TrustedLiveVerifier,
    _run_current_benchmark,
    _run_current_tests,
    _resolve_repository_path,
    verify_release,
)
from vanjaro_cli.release import verifier
from vanjaro_cli.release.test_evidence import run_governed_tests

MODULE_DIR = Path(verifier.__file__).parent


def test_public_and_private_compatibility_seams_resolve() -> None:
    assert REQUIRED_GATE_IDS is verifier.REQUIRED_GATE_IDS
    assert ReleaseVerificationError is verifier.ReleaseVerificationError
    assert TrustedLiveVerifier is verifier.TrustedLiveVerifier
    assert PytestRunObservation is verifier.PytestRunObservation
    assert _run_current_benchmark is verifier._run_current_benchmark
    assert _run_current_tests is run_governed_tests
    assert _resolve_repository_path is verifier._resolve_repository_path
    assert verify_release is verifier.verify_release


def test_release_verifier_module_boundaries() -> None:
    assert len(Path(verifier.__file__).read_text(encoding="utf-8").splitlines()) <= 350
    for name in (
        "gates.py",
        "paths.py",
        "benchmark_verification.py",
        "project_verification.py",
        "control_verification.py",
    ):
        tree = ast.parse((MODULE_DIR / name).read_text(encoding="utf-8"))
        imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        assert all("verifier" not in ast.unparse(node) for node in imports)


def test_each_release_responsibility_has_one_intended_owner() -> None:
    owners = {
        "gates": ("REQUIRED_GATE_IDS", "GateLedger"),
        "paths": (
            "_resolve_repository_path",
            "_verify_reference",
            "_read_png_dimensions",
            "_json_object",
        ),
        "benchmark_verification": ("_verify_benchmark", "_run_current_benchmark"),
        "project_verification": (
            "_verify_project",
            "_verify_project_quality",
            "_verify_live_receipt",
        ),
        "control_verification": (
            "_verify_compatibility",
            "_verify_tests",
            "_verify_secret_scan",
            "_verify_determinism",
            "_verify_performance",
            "_verify_controls",
        ),
    }
    for module_name, names in owners.items():
        module = __import__(f"vanjaro_cli.release.{module_name}", fromlist=["*"])
        for name in names:
            value = getattr(module, name)
            if inspect.isfunction(value) or inspect.isclass(value):
                assert value.__module__ == module.__name__
