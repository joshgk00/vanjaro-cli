"""Tests for deterministic Design Document v1 serialization."""

from __future__ import annotations

import json

import pytest

from vanjaro_cli.design.models import DesignDocument
from vanjaro_cli.design.serialization import (
    DesignDocumentSerializationError,
    deserialize_design_document,
    read_design_document,
    serialize_design_document,
    stable_design_id,
    write_design_document,
)

from .test_design_models import make_design_document_data


def test_serialize_design_document_is_byte_stable_and_keeps_array_order() -> None:
    document = DesignDocument.model_validate(make_design_document_data())

    first = serialize_design_document(document)
    second = serialize_design_document(document)

    assert first.encode("utf-8") == second.encode("utf-8")
    assert first.endswith("\n")
    assert not first.endswith("\n\n")
    assert '\n  "analysis": {' in first
    serialized_data = json.loads(first)
    assert serialized_data["pages"][0]["breakpoints"] == ["desktop", "mobile"]
    assert [
        candidate["role"]
        for candidate in serialized_data["pages"][0]["sections"][0][
            "candidate_roles"
        ]
    ] == ["feature_cards", "gallery"]


def test_serialize_can_exclude_documented_volatile_capture_time() -> None:
    first_data = make_design_document_data()
    second_data = make_design_document_data()
    second_data["source"]["captured_at"] = "2026-07-16T12:01:00Z"
    first = DesignDocument.model_validate(first_data)
    second = DesignDocument.model_validate(second_data)

    assert serialize_design_document(first) != serialize_design_document(second)
    assert serialize_design_document(
        first, exclude_volatile_fields=True
    ) == serialize_design_document(second, exclude_volatile_fields=True)


def test_deserialize_design_document_accepts_utf8_bytes() -> None:
    data = make_design_document_data()
    data["pages"][0]["title"] = "Café"
    document = DesignDocument.model_validate(data)

    loaded = deserialize_design_document(
        serialize_design_document(document).encode("utf-8")
    )

    assert loaded == document
    assert loaded.pages[0].title == "Café"


def test_deserialize_design_document_reports_json_location() -> None:
    with pytest.raises(DesignDocumentSerializationError) as exc_info:
        deserialize_design_document('{"schema_version":')

    assert "line 1" in str(exc_info.value)
    assert "column" in str(exc_info.value)


def test_deserialize_design_document_reports_model_validation() -> None:
    with pytest.raises(
        DesignDocumentSerializationError, match="schema_version"
    ):
        deserialize_design_document("{}")


def test_write_and_read_design_document_use_utf8(tmp_path) -> None:
    data = make_design_document_data()
    data["pages"][0]["title"] = "Crème brûlée"
    document = DesignDocument.model_validate(data)
    path = tmp_path / "design-document.json"

    write_design_document(path, document)
    loaded = read_design_document(path)

    assert loaded == document
    assert path.read_bytes().endswith(b"\n")
    assert "Crème brûlée".encode("utf-8") in path.read_bytes()


def test_stable_design_id_is_source_derived_and_repeatable() -> None:
    first = stable_design_id("Feature Cards", "https://example.com/", 3)

    assert first == stable_design_id("Feature Cards", "https://example.com/", 3)
    assert first != stable_design_id("Feature Cards", "https://example.com/", 4)
    assert first.startswith("feature-cards-")
    assert len(first.rsplit("-", 1)[1]) == 12


def test_stable_design_id_rejects_missing_identity() -> None:
    with pytest.raises(ValueError, match="source identity"):
        stable_design_id("section")
