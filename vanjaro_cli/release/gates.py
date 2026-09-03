"""Release gate definitions and deterministic result ledger."""

from __future__ import annotations

from vanjaro_cli.release.models import GateResult

_SOURCE_KINDS = ("live_html", "figma", "image")
_EXTRACTION_THRESHOLDS = {
    "section_boundary_precision": 0.90,
    "section_boundary_recall": 0.90,
    "visitor_content_retention": 0.95,
    "group_field_association_accuracy": 0.95,
}
_MATCHER_THRESHOLDS = {
    "template_top1_accuracy": 0.85,
    "template_top3_accuracy": 0.95,
    "high_confidence_precision": 0.90,
}
_PROJECT_QUALITY_THRESHOLDS = {
    "eligible_section_editable_coverage": 0.85,
    "native_agency_component_ratio": 0.90,
    "body_without_generic_fallback": 0.90,
    "desktop_tablet_mobile_evidence": 1.0,
}
_CAPTURE_DIMENSIONS = {
    "desktop": (1440, 900),
    "tablet": (768, 1024),
    "mobile": (390, 844),
}


def _required_gate_ids() -> tuple[str, ...]:
    gates = ["compatibility-policy"]
    for source_kind in _SOURCE_KINDS:
        gates.append(f"benchmark-provenance-{source_kind}")
        gates.extend(
            f"quality-{metric}-{source_kind}"
            for metric in (*_EXTRACTION_THRESHOLDS, *_MATCHER_THRESHOLDS)
        )
        gates.extend(
            (
                f"project-ready-{source_kind}",
                f"effort-reduction-{source_kind}",
                f"live-smoke-{source_kind}",
            )
        )
    gates.extend(f"quality-{metric}" for metric in _PROJECT_QUALITY_THRESHOLDS)
    gates.extend(
        (
            "non-integration-tests",
            "secret-scan",
            "deterministic-artifacts",
            "performance-budgets",
            "structured-diagnostics",
            "recovery-tests",
            "contract-migrations",
            "import-boundaries",
        )
    )
    return tuple(gates)


REQUIRED_GATE_IDS = _required_gate_ids()


class ReleaseVerificationError(ValueError):
    """Raised when the release contract itself is malformed or unreadable."""


class _GateLedger:
    def __init__(self) -> None:
        self._results = {
            gate_id: GateResult(
                gate_id=gate_id,
                status="incomplete",
                reason_codes=("missing-evidence",),
            )
            for gate_id in REQUIRED_GATE_IDS
        }

    def set(
        self,
        gate_id: str,
        status: str,
        *reason_codes: str,
        evidence: tuple[str, ...] = (),
    ) -> None:
        if gate_id not in self._results:
            raise AssertionError(f"unknown release gate {gate_id}")
        self._results[gate_id] = GateResult(
            gate_id=gate_id,
            status=status,
            reason_codes=tuple(sorted(set(reason_codes))),
            evidence_sha256=tuple(sorted(set(evidence))),
        )

    def report(self) -> tuple[GateResult, ...]:
        return tuple(self._results[gate_id] for gate_id in sorted(self._results))


SOURCE_KINDS = _SOURCE_KINDS
EXTRACTION_THRESHOLDS = _EXTRACTION_THRESHOLDS
MATCHER_THRESHOLDS = _MATCHER_THRESHOLDS
PROJECT_QUALITY_THRESHOLDS = _PROJECT_QUALITY_THRESHOLDS
CAPTURE_DIMENSIONS = _CAPTURE_DIMENSIONS
GateLedger = _GateLedger

__all__ = [
    "CAPTURE_DIMENSIONS",
    "EXTRACTION_THRESHOLDS",
    "GateLedger",
    "MATCHER_THRESHOLDS",
    "PROJECT_QUALITY_THRESHOLDS",
    "REQUIRED_GATE_IDS",
    "ReleaseVerificationError",
    "SOURCE_KINDS",
]
