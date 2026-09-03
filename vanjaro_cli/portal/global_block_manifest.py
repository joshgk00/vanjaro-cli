"""Persistent state helpers for resumable project global-block operations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class ProjectGlobalBlockError(ValueError):
    """Raised when shared chrome cannot be reconciled without ambiguity."""


def global_block_content_hash(components: object, styles: object) -> str:
    """Return the canonical desired/live hash used across global-block stages."""

    raw = json.dumps(
        {"content_json": components, "style_json": styles},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_global_block_manifest(path: Path) -> dict[str, Any]:
    """Load and validate a project-owned global-block manifest."""

    if not path.is_file():
        return {"schema_version": "1.0", "blocks": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectGlobalBlockError(f"cannot read global manifest: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("blocks"), list):
        raise ProjectGlobalBlockError("global manifest has an unexpected format")
    return payload


def persist_global_block_manifest(
    path: Path,
    desired: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    prior: dict[str, dict[str, Any]],
) -> None:
    """Atomically merge successful records in desired-block order."""

    merged = {**prior, **records}
    write_json(
        path,
        {
            "schema_version": "1.0",
            "blocks": [merged[item["key"]] for item in desired if item["key"] in merged],
        },
    )


def write_json(path: Path, value: object) -> None:
    """Atomically write a deterministic JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


__all__ = [
    "ProjectGlobalBlockError",
    "global_block_content_hash",
    "load_global_block_manifest",
    "persist_global_block_manifest",
    "write_json",
]
