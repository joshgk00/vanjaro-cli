#!/usr/bin/env python3
"""Generate the public release evidence JSON Schemas."""

from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path
import sys
from typing import Final

from pydantic import BaseModel

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from vanjaro_cli.release.models import (
    ControlEvidenceReceipt,
    LiveAttestationReceipt,
    LiveEvidenceReceipt,
    ProjectEffortEvidence,
    ProjectQualityEvidence,
    ProjectReleaseReceipt,
    ReleaseContract,
    TestEvidenceReceipt,
    TestPolicy,
)


SCHEMA_DIRECTORY: Path = REPOSITORY_ROOT / "schemas" / "release"
SCHEMA_DRAFT: Final = "https://json-schema.org/draft/2020-12/schema"

# Public API: tests and documentation tooling use this as the authoritative set.
SCHEMA_MODELS: Final[tuple[tuple[str, type[BaseModel]], ...]] = (
    ("release-contract.schema.json", ReleaseContract),
    ("test-policy.schema.json", TestPolicy),
    ("test-evidence-receipt.schema.json", TestEvidenceReceipt),
    ("control-evidence-receipt.schema.json", ControlEvidenceReceipt),
    ("project-quality-evidence.schema.json", ProjectQualityEvidence),
    ("project-effort-evidence.schema.json", ProjectEffortEvidence),
    ("project-release-receipt.schema.json", ProjectReleaseReceipt),
    ("live-evidence-receipt.schema.json", LiveEvidenceReceipt),
    ("live-attestation-receipt.schema.json", LiveAttestationReceipt),
)


def canonical_json(value: object) -> str:
    """Return canonical public-file JSON: UTF-8-safe, sorted, LF, final LF."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _normalize_schema(value: object) -> object:
    """Remove Pydantic's version-sensitive inferred presentation metadata.

    Field titles are cosmetic and have changed between otherwise compatible
    Pydantic releases. Keeping model-object titles makes definitions readable;
    dropping inferred field titles stabilizes bytes without changing validation.
    """

    if isinstance(value, dict):
        # Pydantic has varied both of these presentation-only details between
        # minor releases: titles on mapping fields, and a redundant string type
        # beside a string enum/const.  Model-object titles remain useful and
        # stable, while mappings are already named by their owning property.
        is_model_object = (
            value.get("type") == "object"
            and ("properties" in value or value.get("additionalProperties") is False)
        )
        normalized = {
            key: _normalize_schema(child)
            for key, child in value.items()
            if key != "title" or is_model_object
        }
        string_values = normalized.get("enum")
        string_const = normalized.get("const")
        if normalized.get("type") == "string" and (
            isinstance(string_const, str)
            or (
                isinstance(string_values, list)
                and string_values
                and all(isinstance(item, str) for item in string_values)
            )
        ):
            normalized.pop("type")
        return normalized
    if isinstance(value, list):
        return [_normalize_schema(child) for child in value]
    return value


def rendered_schemas() -> dict[str, str]:
    """Render every declared public schema without touching the filesystem."""

    rendered: dict[str, str] = {}
    for filename, model in SCHEMA_MODELS:
        schema = _normalize_schema(model.model_json_schema(mode="validation"))
        assert isinstance(schema, dict)
        schema["$schema"] = SCHEMA_DRAFT
        schema["$id"] = filename
        rendered[filename] = canonical_json(schema)
    return rendered


def _drift(filename: str, expected: str, actual: str | None) -> str:
    if actual is None:
        return f"missing schema: schemas/release/{filename}"
    diff = difflib.unified_diff(
        actual.splitlines(),
        expected.splitlines(),
        fromfile=f"schemas/release/{filename} (on disk)",
        tofile=f"schemas/release/{filename} (generated)",
        lineterm="",
    )
    return "\n".join(diff)


def generate(*, check: bool = False) -> int:
    """Write declared schemas, or report drift without writing in check mode."""

    expected = rendered_schemas()
    drift: list[str] = []
    for filename, payload in expected.items():
        path = SCHEMA_DIRECTORY / filename
        if check:
            try:
                actual = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                actual = None
            except (OSError, UnicodeError) as exc:
                drift.append(f"cannot read {path}: {exc}")
                continue
            if actual != payload:
                drift.append(_drift(filename, payload, actual))
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8", newline="\n")

    if drift:
        print("release schema drift detected:", file=sys.stderr)
        print("\n\n".join(drift), file=sys.stderr)
        return 1
    if check:
        print(f"release schemas match models ({len(expected)} files)")
    else:
        print(f"generated {len(expected)} release schemas in {SCHEMA_DIRECTORY}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report schema drift and exit nonzero without writing",
    )
    args = parser.parse_args(argv)
    return generate(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
