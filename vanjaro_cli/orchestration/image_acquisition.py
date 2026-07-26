"""Safe, dependency-free acquisition of workspace-local reference images."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from typing import Any
from urllib.parse import urlsplit

from vanjaro_cli.project.models import ProjectSource


_SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class ImageAcquisitionError(ValueError):
    """Categorized local image or evidence failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        source_id: str,
        recommended_action: str,
    ) -> None:
        self.code = code
        self.source_id = source_id
        self.recommended_action = recommended_action
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AcquiredReferenceImage:
    """Verified raster evidence and its deterministic identity."""

    path: Path
    relative_path: Path
    mime_type: str
    width: int
    height: int
    byte_size: int
    sha256: str


def resolve_workspace_file(
    root: Path,
    reference: str,
    *,
    source_id: str,
    label: str,
) -> tuple[Path, Path]:
    """Resolve one local regular file and reject URLs, escapes, and directories."""

    root = root.expanduser().resolve()
    parsed = urlsplit(reference)
    if parsed.scheme in {"http", "https"}:
        raise ImageAcquisitionError(
            f"remote_{label}_unsupported",
            f"{label.replace('_', ' ')} for source {source_id!r} must be workspace-local: {reference}",
            source_id=source_id,
            recommended_action="Copy the file into the project sources/ directory and update project.json.",
        )
    path = Path(reference).expanduser()
    absolute = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise ImageAcquisitionError(
            f"{label}_outside_workspace",
            f"{label.replace('_', ' ')} for source {source_id!r} escapes the project workspace: {reference}",
            source_id=source_id,
            recommended_action="Copy the file into the project sources/ directory and use a workspace-relative path.",
        ) from exc
    if not absolute.exists():
        raise ImageAcquisitionError(
            f"{label}_missing",
            f"{label.replace('_', ' ')} for source {source_id!r} does not exist: {reference}",
            source_id=source_id,
            recommended_action="Add the declared file inside the project workspace and retry.",
        )
    if not absolute.is_file():
        raise ImageAcquisitionError(
            f"{label}_not_file",
            f"{label.replace('_', ' ')} for source {source_id!r} is not a regular file: {reference}",
            source_id=source_id,
            recommended_action="Reference one regular file rather than a directory or special file.",
        )
    return absolute, relative


def acquire_reference_image(root: Path, source: ProjectSource) -> AcquiredReferenceImage:
    """Validate, identify, dimension, and hash one declared raster source."""

    path, relative = resolve_workspace_file(
        root, source.reference, source_id=source.id, label="image"
    )
    if path.suffix.casefold() not in _SUPPORTED_EXTENSIONS:
        raise ImageAcquisitionError(
            "image_type_unsupported",
            f"image source {source.id!r} must be PNG, JPEG, or WebP: {source.reference}",
            source_id=source.id,
            recommended_action="Export the reference as .png, .jpg/.jpeg, or .webp and retry.",
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ImageAcquisitionError(
            "image_read_failed",
            f"cannot read image source {source.id!r}: {exc}",
            source_id=source.id,
            recommended_action="Check file permissions and retry.",
        ) from exc
    try:
        mime_type, width, height = _image_identity(payload)
    except ValueError as exc:
        raise ImageAcquisitionError(
            "image_decode_failed",
            f"image source {source.id!r} is not a supported valid raster: {exc}",
            source_id=source.id,
            recommended_action="Re-export the image as a valid PNG, JPEG, or WebP file.",
        ) from exc
    expected_extensions = {
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "image/webp": {".webp"},
    }[mime_type]
    if path.suffix.casefold() not in expected_extensions:
        raise ImageAcquisitionError(
            "image_extension_mismatch",
            f"image source {source.id!r} has {mime_type} bytes but extension {path.suffix!r}",
            source_id=source.id,
            recommended_action="Rename or re-export the file so its extension matches its encoded type.",
        )
    return AcquiredReferenceImage(
        path=path,
        relative_path=relative,
        mime_type=mime_type,
        width=width,
        height=height,
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def resolve_evidence_file(root: Path, source: ProjectSource) -> tuple[Path, Path]:
    """Resolve the required evidence sidecar for one image source."""

    if source.evidence_reference is None:
        raise ImageAcquisitionError(
            "image_evidence_missing",
            f"image source {source.id!r} has no evidence sidecar",
            source_id=source.id,
            recommended_action=(
                f"Declare --image-evidence {source.id}=sources/{source.id}.evidence.json "
                "during project init or set evidence_reference in project.json."
            ),
        )
    path, relative = resolve_workspace_file(
        root,
        source.evidence_reference,
        source_id=source.id,
        label="image_evidence",
    )
    if path.suffix.casefold() != ".json":
        raise ImageAcquisitionError(
            "image_evidence_type_unsupported",
            f"image evidence for source {source.id!r} must be a JSON file: {source.evidence_reference}",
            source_id=source.id,
            recommended_action="Use the normalized image evidence JSON sidecar emitted by the evidence workflow.",
        )
    return path, relative


def load_image_evidence(path: Path, source: ProjectSource) -> Any:
    """Parse a strict normalized sidecar while retaining a categorized error."""

    from pydantic import ValidationError

    from vanjaro_cli.design.image_evidence import ImageEvidenceSet

    try:
        payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ImageAcquisitionError(
            "image_evidence_read_failed",
            f"cannot read image evidence for source {source.id!r}: {exc}",
            source_id=source.id,
            recommended_action="Check sidecar permissions and retry.",
        ) from exc
    try:
        return ImageEvidenceSet.model_validate_json(payload)
    except ValidationError as exc:
        raise ImageAcquisitionError(
            "image_evidence_invalid",
            f"image evidence for source {source.id!r} is invalid: {exc}",
            source_id=source.id,
            recommended_action="Regenerate or repair the normalized image evidence sidecar.",
        ) from exc


def validate_evidence_identity(
    evidence: Any, source: ProjectSource, image: AcquiredReferenceImage
) -> None:
    """Give actionable hash and pixel-dimension errors before adapter dispatch."""

    viewport = source.viewport
    assert viewport is not None and source.breakpoint is not None
    observations = list(getattr(evidence, "observations", ()))
    owned = [
        item
        for item in observations
        if getattr(item, "page_slug", None) == source.page_reference
        and getattr(item, "breakpoint", None) == source.breakpoint
        and getattr(getattr(item, "viewport", None), "width", None) == viewport.width
        and getattr(getattr(item, "viewport", None), "height", None) == viewport.height
    ]
    if owned and all(getattr(item, "source_sha256", None) != image.sha256 for item in owned):
        raise ImageAcquisitionError(
            "image_evidence_hash_mismatch",
            f"image evidence for source {source.id!r} was generated from different image bytes",
            source_id=source.id,
            recommended_action="Regenerate the evidence sidecar from the current image file.",
        )
    matching = [
        item for item in owned if getattr(item, "source_sha256", None) == image.sha256
    ]
    if matching and all(
        getattr(item, "image_width", None) != image.width
        or getattr(item, "image_height", None) != image.height
        for item in matching
    ):
        raise ImageAcquisitionError(
            "image_evidence_dimension_mismatch",
            f"image evidence for source {source.id!r} records dimensions that differ from {image.width}x{image.height}",
            source_id=source.id,
            recommended_action="Regenerate the evidence sidecar with the current full-resolution image.",
        )


def _image_identity(payload: bytes) -> tuple[str, int, int]:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(payload) < 24 or payload[12:16] != b"IHDR":
            raise ValueError("truncated PNG header")
        width, height = struct.unpack(">II", payload[16:24])
        return _positive("image/png", width, height)
    if payload.startswith(b"\xff\xd8"):
        width, height = _jpeg_dimensions(payload)
        return _positive("image/jpeg", width, height)
    if len(payload) >= 16 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        width, height = _webp_dimensions(payload)
        return _positive("image/webp", width, height)
    raise ValueError("unrecognized PNG, JPEG, or WebP signature")


def _positive(mime_type: str, width: int, height: int) -> tuple[str, int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    return mime_type, width, height


def _jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    index = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while index < len(payload):
        while index < len(payload) and payload[index] != 0xFF:
            index += 1
        while index < len(payload) and payload[index] == 0xFF:
            index += 1
        if index >= len(payload):
            break
        marker = payload[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(payload):
            break
        length = int.from_bytes(payload[index:index + 2], "big")
        if length < 2 or index + length > len(payload):
            break
        if marker in sof:
            if length < 7:
                break
            height = int.from_bytes(payload[index + 3:index + 5], "big")
            width = int.from_bytes(payload[index + 5:index + 7], "big")
            return width, height
        index += length
    raise ValueError("JPEG has no readable frame dimensions")


def _webp_dimensions(payload: bytes) -> tuple[int, int]:
    offset = 12
    while offset + 8 <= len(payload):
        kind = payload[offset:offset + 4]
        size = int.from_bytes(payload[offset + 4:offset + 8], "little")
        data = payload[offset + 8:offset + 8 + size]
        if len(data) != size:
            break
        if kind == b"VP8X" and len(data) >= 10:
            return 1 + int.from_bytes(data[4:7], "little"), 1 + int.from_bytes(data[7:10], "little")
        if kind == b"VP8L" and len(data) >= 5 and data[0] == 0x2F:
            bits = int.from_bytes(data[1:5], "little")
            return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
        if kind == b"VP8 " and len(data) >= 10 and data[3:6] == b"\x9d\x01\x2a":
            return int.from_bytes(data[6:8], "little") & 0x3FFF, int.from_bytes(data[8:10], "little") & 0x3FFF
        offset += 8 + size + (size & 1)
    raise ValueError("WebP has no readable frame dimensions")


__all__ = [
    "AcquiredReferenceImage",
    "ImageAcquisitionError",
    "acquire_reference_image",
    "load_image_evidence",
    "resolve_evidence_file",
    "resolve_workspace_file",
    "validate_evidence_identity",
]
