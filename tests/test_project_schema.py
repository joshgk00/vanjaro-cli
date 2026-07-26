"""Contract tests for the committed agency project manifest schema."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.project import ProjectManifest


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "agency-project-v1.schema.json"
SCHEMA_METADATA_KEYS = {"$id", "$schema", "description", "title"}


def test_committed_project_schema_tracks_pydantic_contract() -> None:
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    generated = ProjectManifest.model_json_schema()
    for key in SCHEMA_METADATA_KEYS:
        committed.pop(key, None)
        generated.pop(key, None)
    assert committed == generated


def test_project_schema_is_strict_versioned_and_requires_isolation_fields() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("agency-project-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert {"target", "agency_pack", "sources", "stages", "approvals", "audit"} <= set(
        schema["required"]
    )
