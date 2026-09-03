"""Governed, reproducible pytest evidence capture without portal authority."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import subprocess
import sys
from typing import Callable, NamedTuple

from pydantic import ValidationError

from vanjaro_cli.release.models import ArtifactReference, TestEvidenceReceipt, TestPolicy
from vanjaro_cli.reliability.artifacts import (
    ArtifactContractError,
    canonical_json_bytes,
    canonical_json_sha256,
    load_strict_json,
)


GOVERNED_TEST_COMMAND = "python -m pytest -m not integration -q"


class TestEvidenceError(ValueError):
    """Raised when governed test evidence cannot be safely prepared."""


class PytestRunObservation(NamedTuple):
    collected: int
    passed: int
    failed: int
    errors: int
    deselected: int
    node_ids: tuple[str, ...]


TestRunner = Callable[[Path, TestPolicy], PytestRunObservation]


def contains_link_or_reparse(candidate: Path) -> bool:
    """Reject links and Windows junctions in every existing lexical component."""

    absolute = candidate.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            metadata = os.lstat(current)
        except OSError:
            continue
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or (reparse_flag and attributes & reparse_flag):
            return True
    return False


def repository_root(path: Path) -> Path:
    requested = path.expanduser().absolute()
    if contains_link_or_reparse(requested):
        raise TestEvidenceError("repository root cannot contain a symlink or reparse point")
    resolved = requested.resolve()
    if not resolved.is_dir():
        raise TestEvidenceError("repository root must be an existing directory")
    return resolved


def repository_path(
    root: Path, path: Path, *, label: str, must_exist: bool = False
) -> Path:
    requested = path.expanduser()
    raw = str(requested)
    posix = PurePosixPath(raw)
    windows = PureWindowsPath(raw)
    if not requested.is_absolute() and (
        windows.is_absolute() or windows.drive
        or ".." in posix.parts or ".." in windows.parts
    ):
        raise TestEvidenceError(f"{label} must be a repository-local path")
    requested = requested.absolute() if requested.is_absolute() else (root / requested).absolute()
    if contains_link_or_reparse(requested):
        raise TestEvidenceError(f"{label} cannot contain a symlink or reparse point")
    resolved = requested.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise TestEvidenceError(f"{label} must be inside repository root") from exc
    if must_exist and not resolved.is_file():
        raise TestEvidenceError(f"{label} must be an existing file")
    return resolved


def load_test_policy(path: Path) -> TestPolicy:
    try:
        policy = TestPolicy.model_validate(load_strict_json(path))
    except (ArtifactContractError, ValidationError) as exc:
        raise TestEvidenceError(f"invalid test policy: {exc}") from exc
    if policy.command != GOVERNED_TEST_COMMAND:
        raise TestEvidenceError("unsupported governed test command")
    return policy


def discover_test_source_files(root: Path, globs: tuple[str, ...]) -> tuple[ArtifactReference, ...]:
    discovered: dict[str, ArtifactReference] = {}
    try:
        for pattern in globs:
            matches = tuple(root.glob(pattern))
            if not matches:
                raise TestEvidenceError(f"test source glob matched no files: {pattern}")
            for candidate in matches:
                if candidate.is_dir():
                    continue
                if contains_link_or_reparse(candidate):
                    raise TestEvidenceError("test source scope contains a symlink or reparse point")
                resolved = candidate.resolve()
                relative = resolved.relative_to(root).as_posix()
                if resolved.is_file():
                    discovered[relative] = ArtifactReference(
                        path=relative,
                        sha256=hashlib.sha256(resolved.read_bytes()).hexdigest(),
                    )
    except (OSError, ValueError) as exc:
        if isinstance(exc, TestEvidenceError):
            raise
        raise TestEvidenceError("test source scope is invalid") from exc
    if not discovered:
        raise TestEvidenceError("test source scope contains no files")
    return tuple(discovered[path] for path in sorted(discovered))


def build_test_receipt(
    policy: TestPolicy,
    observation: PytestRunObservation,
    source_files: tuple[ArtifactReference, ...],
) -> TestEvidenceReceipt:
    if observation.failed or observation.errors or observation.passed != observation.collected:
        raise TestEvidenceError("governed tests did not pass completely")
    if observation.deselected != policy.allowed_deselected:
        raise TestEvidenceError("governed tests produced an unexpected deselection count")
    node_ids = tuple(sorted(observation.node_ids))
    if not node_ids or len(node_ids) != len(set(node_ids)):
        raise TestEvidenceError("pytest collection produced an invalid node-ID set")
    records = [item.model_dump(mode="json") for item in source_files]
    return TestEvidenceReceipt(
        command=policy.command,
        collected=observation.collected,
        passed=observation.passed,
        failed=observation.failed,
        errors=observation.errors,
        deselected=observation.deselected,
        allowed_deselected=policy.allowed_deselected,
        node_ids=node_ids,
        node_ids_sha256=canonical_json_sha256(list(node_ids)),
        source_tree_sha256=canonical_json_sha256(records),
    )


def expected_observation(receipt: TestEvidenceReceipt) -> PytestRunObservation:
    return PytestRunObservation(
        collected=receipt.collected,
        passed=receipt.passed,
        failed=receipt.failed,
        errors=receipt.errors,
        deselected=receipt.deselected,
        node_ids=tuple(sorted(receipt.node_ids)),
    )


def sanitized_test_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """Return only process essentials; credentials/configuration are never inherited."""

    allowed = {
        "COMSPEC", "HOME", "HOMEDRIVE", "HOMEPATH", "LANG", "LC_ALL",
        "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR",
        "USERPROFILE", "WINDIR",
    }
    inherited = os.environ if source is None else source
    environment = {
        key: value for key, value in inherited.items()
        if key.upper() in allowed
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run_governed_tests(root: Path, policy: TestPolicy) -> PytestRunObservation:
    """Execute exactly the governed pytest command and observe its complete node set."""

    if policy.command != GOVERNED_TEST_COMMAND:
        raise ValueError("unsupported governed test command")
    environment = sanitized_test_environment()
    collect = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "not integration"],
        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900, check=False,
    )
    if collect.returncode != 0:
        raise ValueError("pytest collection failed")
    node_ids = tuple(sorted(
        line.strip() for line in collect.stdout.splitlines()
        if "::" in line and not line.startswith((" ", "="))
    ))
    if not node_ids or len(node_ids) != len(set(node_ids)):
        raise ValueError("pytest collection produced an invalid node-ID set")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-m", "not integration", "-q"],
        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900, check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"

    def count(label: str) -> int:
        match = re.search(rf"(?<!\d)(\d+)\s+{label}\b", output)
        return int(match.group(1)) if match else 0

    observation = PytestRunObservation(
        len(node_ids), count("passed"), count("failed"), count("errors?"),
        count("deselected"), node_ids,
    )
    if completed.returncode == 0 and observation.passed != observation.collected:
        raise ValueError("pytest success summary did not cover the collected node-ID set")
    if completed.returncode != 0 and not (observation.failed or observation.errors):
        raise ValueError("pytest failed without a parseable summary")
    return observation


def contract_fragment(
    *, root: Path, policy_path: Path, receipt_path: Path,
    source_files: tuple[ArtifactReference, ...], receipt: TestEvidenceReceipt | None = None,
) -> dict[str, object]:
    policy_ref = ArtifactReference(
        path=policy_path.relative_to(root).as_posix(),
        sha256=hashlib.sha256(policy_path.read_bytes()).hexdigest(),
    )
    result: dict[str, object] = {
        "policy": policy_ref.model_dump(mode="json"),
        "receipt": (
            ArtifactReference(
                path=receipt_path.relative_to(root).as_posix(),
                sha256=hashlib.sha256(canonical_json_bytes(receipt)).hexdigest(),
            ).model_dump(mode="json") if receipt is not None else {
                "path": receipt_path.relative_to(root).as_posix(), "sha256": None,
            }
        ),
        "source_files": [item.model_dump(mode="json") for item in source_files],
    }
    return {"test_evidence": result}


__all__ = [
    "GOVERNED_TEST_COMMAND", "PytestRunObservation", "TestEvidenceError", "TestRunner",
    "build_test_receipt", "contains_link_or_reparse", "contract_fragment",
    "discover_test_source_files", "expected_observation", "load_test_policy",
    "repository_path", "repository_root", "run_governed_tests", "sanitized_test_environment",
]
