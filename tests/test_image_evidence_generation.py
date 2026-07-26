"""Provider-neutral image detection and normalization contracts."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pytest
import responses

from vanjaro_cli.design.models import BreakpointName, Viewport
from vanjaro_cli.evidence import (
    DetectedEvidenceBundle,
    EvidenceImageInput,
    ImageEvidenceGenerationRequest,
    normalize_detected_evidence,
    strict_detection_schema,
)
from vanjaro_cli.evidence.normalization import ImageEvidenceNormalizationError
from vanjaro_cli.evidence.openai_provider import (
    OpenAIImageEvidenceConfig,
    OpenAIImageEvidenceError,
    OpenAIImageEvidenceProvider,
)


CAPTURED_AT = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def detection_payload(source_ids: tuple[str, ...] = ("image-1",)) -> dict:
    return {
        "observations": [
            {
                "source_id": source_id,
                "page_title": "Evidence Home",
                "sections": [
                    {
                        "id": "hero",
                        "order": 0,
                        "semantic_role": "hero",
                        "role_confidence": 0.95,
                        "bounds": {"x": 0, "y": 0, "width": 640, "height": 480},
                        "layout": {
                            "kind": "stack",
                            "contained": True,
                            "columns": 1,
                            "media_position": None,
                            "alignment": "left",
                            "full_bleed": False,
                            "direction": "vertical",
                            "wrap": False,
                        },
                        "styles": [
                            {
                                "property": "background_color",
                                "value": "#ffffff",
                                "confidence": 0.9,
                            }
                        ],
                        "hidden": False,
                    }
                ],
                "elements": [
                    {
                        "id": "hero-title",
                        "section_id": "hero",
                        "kind": "heading",
                        "role": "section_title",
                        "order": 0,
                        "bounds": {"x": 40, "y": 60, "width": 440, "height": 60},
                        "value": "Build with evidence",
                        "heading_level": 1,
                        "asset_id": None,
                        "group_id": None,
                        "styles": [],
                        "confidence": 0.98,
                    }
                ],
                "groups": [],
                "assets": [],
                "colors": [
                    {"name": "background", "value": "#ffffff", "confidence": 0.9}
                ],
                "spacing": [
                    {"name": "section-padding", "value": "40px", "confidence": 0.8}
                ],
                "typography": [
                    {
                        "role": "display",
                        "font_family": None,
                        "font_size": "48px",
                        "font_weight": "700",
                        "line_height": "1.1",
                        "letter_spacing": None,
                        "confidence": 0.8,
                    }
                ],
                "warnings": [],
            }
            for source_id in source_ids
        ]
    }


def generation_request(source_ids: tuple[str, ...] = ("image-1",)):
    return ImageEvidenceGenerationRequest(
        project_id="agency-image",
        images=tuple(
            EvidenceImageInput(
                source_id=source_id,
                path=Path(f"sources/{source_id}.png"),
                mime_type="image/png",
                payload=(payload := b"png-bytes-" + source_id.encode()),
                sha256=hashlib.sha256(payload).hexdigest(),
                page_slug="home",
                breakpoint=(
                    BreakpointName.DESKTOP
                    if index == 0
                    else BreakpointName.MOBILE
                ),
                viewport=(
                    Viewport(width=1440, height=900)
                    if index == 0
                    else Viewport(width=390, height=844)
                ),
                image_width=640,
                image_height=480,
            )
            for index, source_id in enumerate(source_ids)
        ),
        captured_at=CAPTURED_AT,
    )


def test_structured_output_schema_is_strict_for_every_object() -> None:
    schema = strict_detection_schema()

    def assert_strict(value):
        if isinstance(value, list):
            for item in value:
                assert_strict(item)
        elif isinstance(value, dict):
            assert "default" not in value
            if value.get("type") == "object" and "properties" in value:
                assert value["additionalProperties"] is False
                assert value["required"] == list(value["properties"])
            for item in value.values():
                assert_strict(item)

    assert_strict(schema)


def test_normalization_binds_provider_output_to_exact_request_identity() -> None:
    request = generation_request(("image-1", "image-2"))
    evidence = normalize_detected_evidence(
        request,
        DetectedEvidenceBundle.model_validate(
            detection_payload(("image-1", "image-2"))
        ),
        producer_name="fixture-provider",
        producer_version="1.0",
        model="fixture-model",
        prompt_version="fixture-prompt",
    )

    assert [item.source_sha256 for item in evidence.observations] == [
        item.sha256 for item in request.images
    ]
    assert [item.breakpoint.value for item in evidence.observations] == [
        "desktop",
        "mobile",
    ]
    element = evidence.observations[0].elements[0]
    assert element.value == "Build with evidence"
    assert element.attributes == {"level": 1}
    assert evidence.producer.model == "fixture-model"


def test_normalization_rejects_missing_or_unclaimed_provider_ownership() -> None:
    with pytest.raises(ImageEvidenceNormalizationError, match="missing: image-2"):
        normalize_detected_evidence(
            generation_request(("image-1", "image-2")),
            DetectedEvidenceBundle.model_validate(detection_payload(("image-1",))),
            producer_name="fixture",
            producer_version="1",
            model=None,
            prompt_version=None,
        )


def test_evidence_input_rejects_a_hash_that_does_not_match_payload() -> None:
    with pytest.raises(ValueError, match="does not match"):
        EvidenceImageInput(
            source_id="image-1",
            path=Path("sources/image-1.png"),
            mime_type="image/png",
            payload=b"actual-image-bytes",
            sha256="a" * 64,
            page_slug="home",
            breakpoint=BreakpointName.DESKTOP,
            viewport=Viewport(width=1440, height=900),
            image_width=640,
            image_height=480,
        )


@responses.activate
def test_openai_provider_sends_private_strict_multimodal_request() -> None:
    responses.add(
        responses.POST,
        "https://api.openai.test/v1/responses",
        json={
            "id": "resp_image_123",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(detection_payload()),
                        }
                    ],
                }
            ],
        },
        status=200,
    )
    provider = OpenAIImageEvidenceProvider(
        OpenAIImageEvidenceConfig(
            api_key="test-secret-key",
            model="gpt-test-vision",
            detail="high",
            responses_url="https://api.openai.test/v1/responses",
        )
    )

    result = provider.generate(generation_request())

    assert result.response_id == "resp_image_123"
    assert result.evidence.producer.prompt_version == "vanjaro-image-evidence-1.0"
    sent = json.loads(responses.calls[0].request.body)
    assert sent["store"] is False
    assert sent["text"]["format"]["type"] == "json_schema"
    assert sent["text"]["format"]["strict"] is True
    image = next(
        item
        for item in sent["input"][1]["content"]
        if item["type"] == "input_image"
    )
    assert image["detail"] == "high"
    assert image["image_url"].startswith("data:image/png;base64,")
    assert "test-secret-key" not in json.dumps(sent)
    assert responses.calls[0].request.headers["Authorization"] == "Bearer test-secret-key"


@responses.activate
def test_openai_provider_returns_categorized_http_and_refusal_errors() -> None:
    config = OpenAIImageEvidenceConfig(
        api_key="test-key",
        model="gpt-test",
        responses_url="https://api.openai.test/v1/responses",
    )
    responses.add(
        responses.POST,
        config.responses_url,
        json={"error": {"message": "model unavailable"}},
        status=404,
    )
    with pytest.raises(OpenAIImageEvidenceError) as unavailable:
        OpenAIImageEvidenceProvider(config).generate(generation_request())
    assert unavailable.value.code == "openai_image_evidence_http_error"
    assert unavailable.value.status_code == 404

    responses.replace(
        responses.POST,
        config.responses_url,
        json={
            "id": "resp_refusal",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "refusal", "refusal": "cannot analyze"}],
                }
            ],
        },
        status=200,
    )
    with pytest.raises(OpenAIImageEvidenceError) as refused:
        OpenAIImageEvidenceProvider(config).generate(generation_request())
    assert refused.value.code == "openai_image_evidence_refused"


@pytest.mark.parametrize(
    "body",
    [
        {"output": None},
        {"output": [{"type": "message", "content": None}]},
        {"output": [None]},
    ],
)
@responses.activate
def test_openai_provider_categorizes_malformed_success_shapes(body: dict) -> None:
    config = OpenAIImageEvidenceConfig(
        api_key="test-key",
        model="gpt-test",
        responses_url="https://api.openai.test/v1/responses",
    )
    responses.add(responses.POST, config.responses_url, json=body, status=200)

    with pytest.raises(OpenAIImageEvidenceError) as caught:
        OpenAIImageEvidenceProvider(config).generate(generation_request())

    assert caught.value.code == "openai_image_evidence_invalid_response"


def test_openai_environment_config_requires_key_without_exposing_secrets(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(OpenAIImageEvidenceError) as caught:
        OpenAIImageEvidenceConfig.from_environment()
    assert caught.value.code == "openai_api_key_missing"
    config = OpenAIImageEvidenceConfig(api_key="super-secret", model="gpt-test")
    assert "super-secret" not in repr(config)
