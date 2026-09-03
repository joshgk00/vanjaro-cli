"""Strict JSON normalization and atomic artifact persistence.

The project previously had several almost-identical JSON writers.  Small
differences between those writers (key ordering, NaN handling, and newlines)
made byte-level provenance weaker than the semantic models.  This module is
the single artifact boundary for new agency and release artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from pydantic import BaseModel


class ArtifactContractError(ValueError):
    """Raised when a value or file is outside the strict artifact contract."""


def normalize_json_value(value: object, *, path: str = "$") -> Any:
    """Return a JSON-compatible value while rejecting ambiguous encodings."""

    if isinstance(value, BaseModel):
        return normalize_json_value(value.model_dump(mode="json"), path=path)
    if isinstance(value, Enum):
        return normalize_json_value(value.value, path=path)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArtifactContractError(f"non-finite number is not allowed at {path}")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ArtifactContractError(
                    f"JSON object key at {path} must be a string, got {type(key).__name__}"
                )
            normalized[key] = normalize_json_value(child, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            normalize_json_value(child, path=f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    raise ArtifactContractError(
        f"unsupported artifact value at {path}: {type(value).__name__}"
    )


def canonical_json_bytes(value: object, *, pretty: bool = True) -> bytes:
    """Serialize strict JSON as UTF-8, LF, sorted keys, and one final newline."""

    normalized = normalize_json_value(value)
    options: dict[str, object] = {
        "ensure_ascii": False,
        "sort_keys": True,
        "allow_nan": False,
    }
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    try:
        rendered = json.dumps(normalized, **options)
    except (TypeError, ValueError) as exc:  # defensive boundary around stdlib JSON
        raise ArtifactContractError(str(exc)) from exc
    return (rendered + "\n").encode("utf-8")


def canonical_json_sha256(value: object) -> str:
    """Fingerprint the compact canonical representation of a value."""

    return hashlib.sha256(canonical_json_bytes(value, pretty=False)).hexdigest()


def load_strict_json(path: Path) -> object:
    """Load UTF-8 JSON while rejecting non-finite constants and duplicate keys."""

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArtifactContractError(f"cannot read JSON artifact {path}: {exc}") from exc
    try:
        return json.loads(
            raw,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ArtifactContractError(f"invalid strict JSON artifact {path}: {exc}") from exc


def atomic_write_json(path: Path, value: object, *, pretty: bool = True) -> Path:
    """Validate first, then atomically replace PATH with canonical JSON bytes."""

    payload = canonical_json_bytes(value, pretty=pretty)
    path = path.expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ArtifactContractError(f"cannot create artifact directory {path.parent}: {exc}") from exc

    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise ArtifactContractError(f"cannot write JSON artifact {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return path


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


__all__ = [
    "ArtifactContractError",
    "atomic_write_json",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "load_strict_json",
    "normalize_json_value",
]
