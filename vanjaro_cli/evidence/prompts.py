"""Versioned prompts for visual design evidence extraction."""

from __future__ import annotations

import json

from vanjaro_cli.evidence.models import ImageEvidenceGenerationRequest


IMAGE_EVIDENCE_PROMPT_VERSION = "vanjaro-image-evidence-1.0"

SYSTEM_PROMPT = """You extract auditable website-design evidence from reference images.

Return only the requested structured data. Preserve visible visitor-facing text
exactly, including capitalization and punctuation. Never invent text, links,
action destinations, alt text, original asset URLs, interactions, or content
that is not visible. If text is illegible, use null and emit a warning.

Treat the image as a complete page capture. Identify ordered section boundaries,
semantic roles, visible content elements, editable editorial media regions,
repeated structures, layout, responsive differences, and high-confidence design
tokens. Coordinates must use the original image pixel dimensions supplied with
each source, not a resized model coordinate system. Element bounds must be
contained by their owning section. Orders are zero-based and unique within their
owner.

Use stable kebab-case IDs. When multiple breakpoints show the same page, reuse
the same section IDs and semantic element IDs wherever the evidence supports a
correspondence. Every image or video element must reference one asset. Every
repeat-group field must reference elements owned by that group and section.
Use confidence below 1.0 whenever classification or geometry is uncertain, and
emit explicit warnings for meaningful ambiguity. Return one observation for
each exact source_id and no others."""


def request_instruction(request: ImageEvidenceGenerationRequest) -> str:
    identities = [
        {
            "source_id": item.source_id,
            "page_slug": item.page_slug,
            "breakpoint": item.breakpoint.value,
            "viewport": item.viewport.model_dump(mode="json"),
            "image_pixels": {"width": item.image_width, "height": item.image_height},
            "sha256_prefix": item.sha256[:12],
        }
        for item in request.images
    ]
    return (
        "Analyze the following reference images as evidence for one website page. "
        "Use these exact identities in the observations:\n"
        + json.dumps(identities, ensure_ascii=False, sort_keys=True)
    )


__all__ = [
    "IMAGE_EVIDENCE_PROMPT_VERSION",
    "SYSTEM_PROMPT",
    "request_instruction",
]
