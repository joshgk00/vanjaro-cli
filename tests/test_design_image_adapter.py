"""Pure contract and fail-closed coverage for reference-image evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.design.image_adapter import ImageEvidenceConversionError
from vanjaro_cli.design.image_evidence import ImageEvidenceSet
from vanjaro_cli.design.models import BreakpointName, SourceKind
from vanjaro_cli.design.serialization import serialize_design_document
from vanjaro_cli.design.sources import ImageSourceRequest, ReferenceImage, analyze_source


SHA = "a" * 64
CAPTURED_AT = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _evidence_data() -> dict:
    return {
        "schema_version": "1.0",
        "producer": {
            "name": "annotated-fixture",
            "version": "1.0",
            "model": None,
            "prompt_version": None,
        },
        "observations": [
            {
                "source_sha256": SHA,
                "captured_at": CAPTURED_AT.isoformat(),
                "page_slug": "home",
                "page_title": "Image Evidence Home",
                "breakpoint": "desktop",
                "viewport": {"width": 1440, "height": 900},
                "image_width": 1440,
                "image_height": 900,
                "sections": [
                    {
                        "id": "hero",
                        "order": 0,
                        "semantic_role": "hero",
                        "role_confidence": 0.92,
                        "candidate_roles": [
                            {"role": "banner", "score": 0.64, "evidence": ["top region"]}
                        ],
                        "bounds": {"x": 0, "y": 0, "width": 1440, "height": 600},
                        "layout": {
                            "kind": "split",
                            "contained": True,
                            "columns": 2,
                            "media_position": "right",
                            "alignment": "center",
                            "direction": "horizontal",
                        },
                        "styles": [
                            {
                                "property": "background_color",
                                "value": "#102030",
                                "confidence": 0.98,
                            }
                        ],
                    }
                ],
                "elements": [
                    {
                        "id": "heading-1",
                        "section_id": "hero",
                        "kind": "heading",
                        "role": "title",
                        "order": 0,
                        "bounds": {"x": 100, "y": 100, "width": 520, "height": 80},
                        "value": "Build with evidence",
                        "group_id": "hero-fields",
                        "confidence": 0.97,
                    },
                    {
                        "id": "media-1",
                        "section_id": "hero",
                        "kind": "image",
                        "role": "hero_image",
                        "order": 1,
                        "bounds": {"x": 760, "y": 80, "width": 560, "height": 420},
                        "asset_id": "asset-1",
                        "group_id": "hero-fields",
                        "confidence": 0.91,
                    },
                    {
                        "id": "action-1",
                        "section_id": "hero",
                        "kind": "button",
                        "role": "primary_action",
                        "order": 2,
                        "bounds": {"x": 100, "y": 230, "width": 180, "height": 48},
                        "value": "Start now",
                        "confidence": 0.88,
                    },
                ],
                "groups": [
                    {
                        "id": "hero-fields",
                        "section_id": "hero",
                        "kind": "card",
                        "items": [
                            {
                                "id": "hero-item",
                                "fields": {"title": "heading-1", "image": "media-1"},
                                "confidence": 0.9,
                            }
                        ],
                        "confidence": 0.9,
                    }
                ],
                "assets": [
                    {
                        "id": "asset-1",
                        "kind": "image",
                        "role": "editorial",
                        "bounds": {"x": 760, "y": 80, "width": 560, "height": 420},
                        "confidence": 0.91,
                    }
                ],
                "colors": [{"name": "image-primary", "value": "#102030"}],
                "spacing": [{"name": "image-section-gap", "value": 48}],
                "typography": [{"role": "display", "font_size": "64px", "confidence": 0.7}],
            }
        ],
    }


def _request(*, sha256: str = SHA, evidence: ImageEvidenceSet | None = None) -> ImageSourceRequest:
    evidence = evidence or ImageEvidenceSet.model_validate(_evidence_data())
    return ImageSourceRequest(
        images=(
            ReferenceImage(
                path=Path("sources/home-desktop.png"),
                page_slug="home",
                breakpoint=BreakpointName.DESKTOP,
                viewport_width=1440,
                viewport_height=900,
                sha256=sha256,
            ),
        ),
        project_id="agency-image",
        evidence=evidence,
        captured_at=CAPTURED_AT,
    )


def test_image_adapter_is_deterministic_and_preserves_auditable_evidence() -> None:
    request = _request()
    first = analyze_source(request)
    second = analyze_source(request)

    assert serialize_design_document(first) == serialize_design_document(second)
    assert first.source.kind == SourceKind.IMAGE
    assert first.source.adapter_version == "image-evidence/1.0"
    assert first.source.metadata["images"][0]["sha256"] == SHA
    section = first.pages[0].sections[0]
    assert section.semantic_role == "hero"
    assert section.role_confidence == 0.92
    assert section.provenance[0].bounds.width == 1440
    assert section.provenance[0].metadata["image_evidence_id"] == "hero"
    heading = next(item for item in section.content if item.role == "title")
    assert heading.value == "Build with evidence"
    assert heading.confidence == 0.97
    assert heading.metadata["bounds"]["x"] == 100.0
    assert section.groups[0].items[0].fields["title"] == heading.id
    assert first.tokens.colors["image-primary"].value == "#102030"


def test_image_adapter_never_fabricates_original_assets_or_action_targets() -> None:
    document = analyze_source(_request())
    section = document.pages[0].sections[0]
    action = next(item for item in section.content if item.kind.value == "button")
    asset = document.assets[0]

    assert action.attributes == {}
    assert asset.source_url is None
    assert asset.local_path is None
    assert asset.missing_reason == "Original asset is unavailable from the reference image."
    codes = {item.code for item in document.warnings}
    assert "IMAGE_ACTION_TARGET_UNKNOWN" in codes
    assert "IMAGE_ORIGINAL_ASSET_UNAVAILABLE" in codes
    assert "action_target_unavailable_from_reference_image" in document.analysis.unsupported_traits
    assert "original_asset_unavailable_from_reference_image" in document.analysis.unsupported_traits


def test_image_adapter_rejects_hash_or_unclaimed_evidence_mismatch() -> None:
    with pytest.raises(ImageEvidenceConversionError, match="does not match request hash"):
        analyze_source(_request(sha256="b" * 64))

    payload = _evidence_data()
    extra = deepcopy(payload["observations"][0])
    extra["source_sha256"] = "c" * 64
    extra["page_slug"] = "other"
    payload["observations"].append(extra)
    with pytest.raises(ImageEvidenceConversionError, match="unclaimed observations"):
        analyze_source(_request(evidence=ImageEvidenceSet.model_validate(payload)))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda value: value["observations"][0]["sections"][0]["bounds"].update(
                {"width": 1441}
            ),
            "bounds exceed image dimensions",
        ),
        (
            lambda value: value["observations"][0]["elements"][0].update(
                {"section_id": "missing"}
            ),
            "references missing section",
        ),
        (
            lambda value: value["observations"][0]["elements"][1].update(
                {"asset_id": "missing"}
            ),
            "references missing asset",
        ),
        (
            lambda value: value["observations"][0]["groups"][0]["items"][0][
                "fields"
            ].update({"caption": "missing"}),
            "references missing element",
        ),
        (
            lambda value: value["observations"][0]["elements"][0].update(
                {"group_id": None}
            ),
            "without matching section/group ownership",
        ),
    ],
)
def test_image_evidence_fails_closed_on_bounds_and_dangling_references(
    mutate, message: str
) -> None:
    payload = _evidence_data()
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        ImageEvidenceSet.model_validate(payload)


def test_image_evidence_is_strict_and_rejects_escaping_original_asset_path() -> None:
    payload = _evidence_data()
    payload["observations"][0]["unknown"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ImageEvidenceSet.model_validate(payload)

    payload = _evidence_data()
    payload["observations"][0]["assets"][0]["original_local_path"] = "../secret.png"
    with pytest.raises(ValidationError, match="must not escape"):
        ImageEvidenceSet.model_validate(payload)
