"""Strict artifact and diagnostic contract tests."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.reliability import (
    ArtifactContractError,
    DiagnosticContext,
    atomic_write_json,
    build_diagnostic,
    canonical_json_bytes,
    canonical_json_sha256,
    load_strict_json,
)


def test_canonical_json_is_order_independent_unicode_and_lf() -> None:
    left = {"z": "café", "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "z": "café"}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert canonical_json_sha256(left) == canonical_json_sha256(right)
    assert canonical_json_bytes(left).endswith(b"\n")
    assert b"\r\n" not in canonical_json_bytes(left)
    assert "café".encode() in canonical_json_bytes(left)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_values_fail_before_existing_artifact_is_replaced(
    tmp_path: Path, value: float
) -> None:
    path = tmp_path / "artifact.json"
    path.write_text("owned\n", encoding="utf-8")

    with pytest.raises(ArtifactContractError, match="non-finite"):
        atomic_write_json(path, {"nested": [value]})

    assert path.read_text(encoding="utf-8") == "owned\n"


def test_strict_loader_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"a":NaN}', encoding="utf-8")

    with pytest.raises(ArtifactContractError, match="duplicate"):
        load_strict_json(duplicate)
    with pytest.raises(ArtifactContractError, match="non-finite"):
        load_strict_json(nonfinite)


def test_diagnostic_redacts_authority_urls_queries_and_machine_paths() -> None:
    envelope = build_diagnostic(
        code="release.evidence.invalid",
        category="evidence",
        message=(
            "Authorization: Bearer canary at "
            "http://admin:password@example.test/path?api_key=canary&safe=yes "
            "https://example.test/callback#access_token=fragment-canary "
            "from C:\\Users\\Agency\\private.json"
        ),
        recommended_action="Inspect /home/agency/private/report.json",
        context=DiagnosticContext(artifact_path="qa/report.json"),
    )
    rendered = canonical_json_bytes(envelope).decode()

    assert "canary" not in rendered
    assert "password" not in rendered
    assert "fragment-canary" not in rendered
    assert "C:\\Users" not in rendered
    assert "/home/agency" not in rendered
    assert "[REDACTED]" in rendered
    assert "[LOCAL_PATH]" in rendered


def test_diagnostic_context_rejects_absolute_or_escaping_paths() -> None:
    with pytest.raises(ValidationError, match="relative"):
        DiagnosticContext(artifact_path="C:/secrets/report.json")
    with pytest.raises(ValidationError, match="escape"):
        DiagnosticContext(artifact_path="../report.json")


def test_malformed_url_port_is_redacted_without_raising() -> None:
    envelope = build_diagnostic(
        code="release.url.invalid",
        category="evidence",
        message="provider returned https://example.test:not-a-port/path",
        recommended_action="Review the provider URL.",
    )

    assert "[REDACTED_URL]" in envelope.diagnostic.message
