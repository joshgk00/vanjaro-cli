"""Contract tests for the committed Design Document v1 JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

from vanjaro_cli.design.models import DesignDocument


SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "design-document-v1.schema.json"
)
SCHEMA_METADATA_KEYS = {
    "$id",
    "$schema",
    "description",
    "title",
    "x-validation-notes",
}


def load_committed_schema() -> dict:
    """Load the committed public schema without external dependencies."""

    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_committed_schema_tracks_pydantic_contract() -> None:
    committed = load_committed_schema()
    generated = DesignDocument.model_json_schema()

    for key in SCHEMA_METADATA_KEYS:
        committed.pop(key, None)
        generated.pop(key, None)

    assert committed == generated


def test_schema_declares_version_policy_and_required_artifact_fields() -> None:
    schema = load_committed_schema()

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith("design-document-v1.schema.json")
    assert set(schema["required"]) == {
        "schema_version",
        "source",
        "tokens",
        "assets",
        "pages",
        "warnings",
        "analysis",
    }
    assert schema["properties"]["schema_version"]["pattern"] == "^1\\.0$"
    assert schema["additionalProperties"] is False
    assert "breaking changes require a new major schema" in schema[
        "description"
    ]


def test_schema_exposes_enum_ranges_and_unique_id_annotations() -> None:
    schema = load_committed_schema()

    assert schema["$defs"]["ContentKind"]["enum"] == [
        "heading",
        "text",
        "image",
        "button",
        "link",
        "list",
        "list_item",
        "quote",
        "stat",
        "video",
        "form_placeholder",
        "other",
    ]
    assert schema["$defs"]["CandidateRole"]["properties"]["score"] == {
        "maximum": 1,
        "minimum": 0,
        "title": "Score",
        "type": "number",
    }
    assert schema["properties"]["assets"]["x-unique-by"] == "id"
    assert schema["properties"]["pages"]["x-unique-by"] == "id"
    assert schema["$defs"]["Section"]["properties"]["content"][
        "x-unique-by"
    ] == "id"
