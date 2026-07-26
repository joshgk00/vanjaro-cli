"""Versioned evidence-producer contracts and provider adapters."""

from vanjaro_cli.evidence.models import (
    DetectedEvidenceBundle,
    EvidenceImageInput,
    ImageEvidenceGenerationRequest,
    ImageEvidenceGenerationResult,
    ImageEvidenceProvider,
    ImageEvidenceProviderError,
    strict_detection_schema,
)
from vanjaro_cli.evidence.normalization import normalize_detected_evidence

__all__ = [
    "DetectedEvidenceBundle",
    "EvidenceImageInput",
    "ImageEvidenceGenerationRequest",
    "ImageEvidenceGenerationResult",
    "ImageEvidenceProvider",
    "ImageEvidenceProviderError",
    "normalize_detected_evidence",
    "strict_detection_schema",
]
