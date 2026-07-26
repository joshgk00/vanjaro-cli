"""Deterministic UTF-8 serialization for Design Document v1."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import ValidationError

from vanjaro_cli.design.models import DesignDocument

__all__ = [
    "DesignDocumentSerializationError",
    "deserialize_design_document",
    "read_design_document",
    "serialize_design_document",
    "stable_design_id",
    "write_design_document",
]


class DesignDocumentSerializationError(ValueError):
    """Raised when Design Document JSON cannot be decoded or validated."""


def stable_design_id(prefix: str, *source_parts: str | int) -> str:
    """Return a stable readable ID derived from source identity and position.

    The first component remains human-readable while a short SHA-256 suffix
    prevents collisions between equal labels from different source locations.
    """

    normalized_prefix = re.sub(r"[^a-z0-9]+", "-", prefix.casefold()).strip("-")
    if not normalized_prefix:
        raise ValueError("prefix must contain at least one letter or number")
    if not source_parts:
        raise ValueError("at least one source identity or position is required")

    identity = json.dumps(
        [str(part) for part in source_parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    return f"{normalized_prefix}-{suffix}"


def serialize_design_document(
    document: DesignDocument,
    *,
    exclude_volatile_fields: bool = False,
) -> str:
    """Serialize a document with sorted keys, two-space indentation, and newline.

    Array order is preserved because it carries page, section, and content
    meaning. When ``exclude_volatile_fields`` is true, ``source.captured_at`` is
    omitted for byte-level comparisons across independent analysis runs.
    """

    exclude = {"source": {"captured_at"}} if exclude_volatile_fields else None
    payload = document.model_dump(mode="json", exclude=exclude)
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def deserialize_design_document(serialized: str | bytes) -> DesignDocument:
    """Decode and validate serialized Design Document JSON."""

    try:
        if isinstance(serialized, bytes):
            serialized = serialized.decode("utf-8")
        payload = json.loads(serialized)
        return DesignDocument.model_validate(payload)
    except UnicodeDecodeError as exc:
        raise DesignDocumentSerializationError(
            "Design Document must be valid UTF-8"
        ) from exc
    except json.JSONDecodeError as exc:
        raise DesignDocumentSerializationError(
            f"Invalid Design Document JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except ValidationError as exc:
        raise DesignDocumentSerializationError(
            f"Invalid Design Document: {exc}"
        ) from exc


def write_design_document(path: str | Path, document: DesignDocument) -> None:
    """Write a Design Document as deterministic UTF-8 JSON."""

    Path(path).write_text(serialize_design_document(document), encoding="utf-8")


def read_design_document(path: str | Path) -> DesignDocument:
    """Read and validate a UTF-8 Design Document file."""

    try:
        serialized = Path(path).read_bytes()
    except OSError as exc:
        raise DesignDocumentSerializationError(
            f"Could not read Design Document {path}: {exc}"
        ) from exc
    return deserialize_design_document(serialized)

