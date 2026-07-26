"""OpenAI Responses API adapter for strict visual design evidence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
import requests

from vanjaro_cli.evidence.models import (
    DetectedEvidenceBundle,
    ImageEvidenceGenerationRequest,
    ImageEvidenceGenerationResult,
    ImageEvidenceProviderError,
    strict_detection_schema,
)
from vanjaro_cli.evidence.normalization import (
    ImageEvidenceNormalizationError,
    normalize_detected_evidence,
)
from vanjaro_cli.evidence.prompts import (
    IMAGE_EVIDENCE_PROMPT_VERSION,
    SYSTEM_PROMPT,
    request_instruction,
)


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_IMAGE_EVIDENCE_PROVIDER_VERSION = "1.0"
DEFAULT_IMAGE_EVIDENCE_MODEL = "gpt-5.4"


class OpenAIImageEvidenceError(ImageEvidenceProviderError):
    """Categorized, secret-safe provider failure with recovery guidance."""

    pass


class OpenAIImageEvidenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr
    model: str = Field(min_length=1)
    detail: Literal["low", "high", "auto"] = "high"
    responses_url: str = OPENAI_RESPONSES_URL
    max_output_tokens: int = Field(default=32768, ge=1024, le=128000)
    connect_timeout_seconds: float = Field(default=15, gt=0, le=120)
    read_timeout_seconds: float = Field(default=180, gt=0, le=900)

    @field_validator("model")
    @classmethod
    def normalize_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("OpenAI image evidence model must not be empty")
        return normalized

    @field_validator("responses_url")
    @classmethod
    def validate_responses_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("OpenAI responses URL must use HTTPS (HTTP is local-test only)")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("OpenAI responses URL must be a credential-free endpoint URL")
        return normalized

    @classmethod
    def from_environment(
        cls,
        *,
        model: str | None = None,
        detail: Literal["low", "high", "auto"] = "high",
        max_output_tokens: int = 32768,
    ) -> "OpenAIImageEvidenceConfig":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise OpenAIImageEvidenceError(
                "openai_api_key_missing",
                "OPENAI_API_KEY is not configured for image evidence generation",
                recommended_action=(
                    "Set OPENAI_API_KEY in the process environment or local .env file, "
                    "then retry. The key is never written to project artifacts."
                ),
            )
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        selected_model = (
            model
            or os.environ.get("VANJARO_IMAGE_EVIDENCE_MODEL")
            or DEFAULT_IMAGE_EVIDENCE_MODEL
        )
        return cls(
            api_key=SecretStr(api_key),
            model=selected_model,
            detail=detail,
            responses_url=f"{base_url}/responses",
            max_output_tokens=max_output_tokens,
        )


class OpenAIImageEvidenceProvider:
    """Generate normalized evidence without exposing API details downstream."""

    provider_name = "openai-responses-vision"

    def __init__(
        self,
        config: OpenAIImageEvidenceConfig,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self._session = session or requests.Session()

    def generate(
        self, request: ImageEvidenceGenerationRequest
    ) -> ImageEvidenceGenerationResult:
        request_fingerprint = _request_fingerprint(request, self.config)
        payload = _request_payload(request, self.config)
        headers = {
            "Authorization": f"Bearer {self.config.api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "User-Agent": "vanjaro-cli/image-evidence-1.0",
        }
        try:
            response = self._session.post(
                self.config.responses_url,
                headers=headers,
                json=payload,
                timeout=(
                    self.config.connect_timeout_seconds,
                    self.config.read_timeout_seconds,
                ),
            )
        except requests.Timeout as exc:
            raise OpenAIImageEvidenceError(
                "openai_image_evidence_timeout",
                "OpenAI image evidence generation timed out",
                recommended_action="Retry, reduce the number or size of images, or increase the provider timeout.",
            ) from exc
        except requests.RequestException as exc:
            raise OpenAIImageEvidenceError(
                "openai_image_evidence_transport",
                f"OpenAI image evidence request failed: {exc.__class__.__name__}",
                recommended_action="Check network access and OPENAI_BASE_URL, then retry.",
            ) from exc

        if response.status_code >= 400:
            raise _http_error(response)
        try:
            body = response.json()
        except (requests.JSONDecodeError, ValueError) as exc:
            raise OpenAIImageEvidenceError(
                "openai_image_evidence_invalid_response",
                "OpenAI returned a non-JSON image evidence response",
                recommended_action="Retry the request; if it persists, verify the configured endpoint.",
                status_code=response.status_code,
            ) from exc
        if not isinstance(body, dict):
            raise OpenAIImageEvidenceError(
                "openai_image_evidence_invalid_response",
                "OpenAI returned an unexpected top-level response",
                recommended_action="Retry the request; if it persists, update the provider adapter.",
                status_code=response.status_code,
            )
        text = _extract_output_text(body)
        try:
            detected = DetectedEvidenceBundle.model_validate_json(text)
        except ValidationError as exc:
            raise OpenAIImageEvidenceError(
                "openai_image_evidence_schema_mismatch",
                "OpenAI output did not satisfy the Vanjaro detection contract",
                recommended_action="Retry once; if it persists, review the provider model and prompt versions.",
                status_code=response.status_code,
            ) from exc
        response_id = body.get("id") if isinstance(body.get("id"), str) else None
        try:
            evidence = normalize_detected_evidence(
                request,
                detected,
                producer_name=self.provider_name,
                producer_version=OPENAI_IMAGE_EVIDENCE_PROVIDER_VERSION,
                model=self.config.model,
                prompt_version=IMAGE_EVIDENCE_PROMPT_VERSION,
                metadata={
                    "provider": "openai",
                    "detail": self.config.detail,
                    "response_id": response_id,
                    "request_fingerprint": request_fingerprint,
                },
            )
        except ImageEvidenceNormalizationError as exc:
            raise OpenAIImageEvidenceError(
                "openai_image_evidence_invalid",
                str(exc),
                recommended_action="Regenerate the evidence or correct it with an audited overlay.",
                status_code=response.status_code,
            ) from exc
        return ImageEvidenceGenerationResult(
            evidence=evidence,
            provider=self.provider_name,
            model=self.config.model,
            response_id=response_id,
            request_fingerprint=request_fingerprint,
        )


def _request_payload(
    request: ImageEvidenceGenerationRequest,
    config: OpenAIImageEvidenceConfig,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {"type": "input_text", "text": request_instruction(request)}
    ]
    for image in request.images:
        content.append(
            {
                "type": "input_text",
                "text": (
                    f"source_id={image.source_id}; breakpoint={image.breakpoint.value}; "
                    f"original_pixels={image.image_width}x{image.image_height}"
                ),
            }
        )
        encoded = base64.b64encode(image.payload).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{image.mime_type};base64,{encoded}",
                "detail": config.detail,
            }
        )
    return {
        "model": config.model,
        "store": False,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "vanjaro_image_evidence",
                "strict": True,
                "schema": strict_detection_schema(),
            }
        },
        "max_output_tokens": config.max_output_tokens,
    }


def _request_fingerprint(
    request: ImageEvidenceGenerationRequest,
    config: OpenAIImageEvidenceConfig,
) -> str:
    value = {
        "project_id": request.project_id,
        "model": config.model,
        "detail": config.detail,
        "prompt_version": IMAGE_EVIDENCE_PROMPT_VERSION,
        "provider_version": OPENAI_IMAGE_EVIDENCE_PROVIDER_VERSION,
        "images": [
            {
                "source_id": item.source_id,
                "sha256": item.sha256,
                "page_slug": item.page_slug,
                "breakpoint": item.breakpoint.value,
                "viewport": item.viewport.model_dump(mode="json"),
                "pixels": [item.image_width, item.image_height],
            }
            for item in request.images
        ],
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _extract_output_text(body: dict[str, Any]) -> str:
    output = body.get("output")
    if not isinstance(output, list):
        raise _invalid_response_shape("output must be a list")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            raise _invalid_response_shape("output items must be objects")
        if item.get("type") != "message":
            continue
        contents = item.get("content")
        if not isinstance(contents, list):
            raise _invalid_response_shape("message content must be a list")
        for content in contents:
            if not isinstance(content, dict):
                raise _invalid_response_shape("message content items must be objects")
            if content.get("type") == "refusal":
                raise OpenAIImageEvidenceError(
                    "openai_image_evidence_refused",
                    "OpenAI declined to analyze the supplied reference image",
                    recommended_action="Review the image and policy requirements, then use a different permitted reference.",
                )
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if not texts:
        reason = body.get("incomplete_details")
        suffix = f" ({reason})" if isinstance(reason, dict) else ""
        raise OpenAIImageEvidenceError(
            "openai_image_evidence_empty",
            "OpenAI returned no structured image evidence" + suffix,
            recommended_action="Retry with a higher output-token limit or fewer images.",
        )
    return "".join(texts)


def _invalid_response_shape(detail: str) -> OpenAIImageEvidenceError:
    return OpenAIImageEvidenceError(
        "openai_image_evidence_invalid_response",
        f"OpenAI returned an unexpected image evidence response: {detail}",
        recommended_action=(
            "Retry the request; if it persists, update the provider adapter."
        ),
    )


def _http_error(response: requests.Response) -> OpenAIImageEvidenceError:
    message = f"OpenAI image evidence request returned HTTP {response.status_code}"
    try:
        payload = response.json()
        detail = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
        if isinstance(detail, str) and detail.strip():
            message += ": " + detail.strip()[:300]
    except (requests.JSONDecodeError, ValueError, AttributeError):
        pass
    action = (
        "Check OPENAI_API_KEY and model access, then retry."
        if response.status_code in {401, 403, 404}
        else "Retry after the provider recovers or reduce request size."
    )
    return OpenAIImageEvidenceError(
        "openai_image_evidence_http_error",
        message,
        recommended_action=action,
        status_code=response.status_code,
    )


__all__ = [
    "DEFAULT_IMAGE_EVIDENCE_MODEL",
    "OPENAI_IMAGE_EVIDENCE_PROVIDER_VERSION",
    "OpenAIImageEvidenceConfig",
    "OpenAIImageEvidenceError",
    "OpenAIImageEvidenceProvider",
]
