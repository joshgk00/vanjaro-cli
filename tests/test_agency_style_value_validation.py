"""W1 correction: CSS declaration validity must not depend on platform utility
availability.

``artifacts/test_agency_style_pack_independent.py`` (the root's immutable
baseline) proves the headline regression is fixed: a handful of named values
that have no Bootstrap/Vanjaro utility class mapped to them (``display:
inline-flex``, ``object-fit: fill``, ``position: static``, ``flex-wrap:
wrap-reverse``, ``column-count: auto``) must still be accepted as valid CSS,
and the delivered schema must match ``AgencyStylePayload.model_json_schema()``
exactly. JSON Schema alone does not encode any of this module's *semantic*
value grammar (closed keyword domains, integer sign/range rules, CSS-wide
keywords) -- a payload can satisfy the schema's ``type: string`` and still be
nonsense CSS -- so this file exercises the runtime validators directly:
representative valid and near-miss-invalid values per affected property,
CSS-wide keyword handling, integer sign/range edges, keyword casing, that the
pre-existing injection/unsafe-URL rejection is untouched, that legacy
serialization shape is unchanged, and schema parity.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from vanjaro_cli.agency_library.style_payload import (
    AgencyStylePayload,
    AgencyStyleUtility,
    style_utility_key,
)

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "agency-style-library-v1.schema.json"


def _utility(property: str, source_value: str, class_name: str = "cm-example") -> AgencyStyleUtility:
    return AgencyStyleUtility(property=property, source_value=source_value, class_name=class_name)


# --- representative valid values, beyond the Bootstrap utility subset -------


@pytest.mark.parametrize(
    "property_name,value",
    [
        ("display", "inline-flex"),
        ("display", "inline-grid"),
        ("display", "table"),
        ("display", "table-cell"),
        ("display", "flow-root"),
        ("display", "list-item"),
        ("object_fit", "fill"),
        ("object_fit", "scale-down"),
        ("object_fit", "none"),
        ("position", "static"),
        ("flex_wrap", "wrap-reverse"),
        ("column_count", "auto"),
        ("column_count", "1"),
        ("column_count", "12"),
        ("order", "-3"),
        ("order", "0"),
        ("order", "7"),
    ],
)
def test_valid_css_values_beyond_the_platform_utility_subset_are_accepted(
    property_name: str, value: str
) -> None:
    utility = _utility(property_name, value)
    assert utility.source_value == value


# --- near-miss invalid values must still reject -----------------------------


@pytest.mark.parametrize(
    "property_name,value",
    [
        ("display", "banana"),
        ("display", "in-line-flex"),
        ("display", "Flexbox"),
        ("object_fit", "zoom"),
        ("object_fit", "stretch"),
        ("position", "stick"),
        ("position", "float"),
        ("flex_wrap", "no-wrap"),
        ("flex_wrap", "wrap reverse"),
        ("column_count", "0"),
        ("column_count", "-1"),
        ("column_count", "1.5"),
        ("column_count", "two"),
        ("order", "1.5"),
        ("order", "abc"),
        ("order", "+5"),
        ("order", "--1"),
    ],
)
def test_near_miss_invalid_css_values_are_rejected(property_name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _utility(property_name, value)


# --- CSS-wide keywords, where semantically supported ------------------------


@pytest.mark.parametrize(
    "property_name",
    ["display", "object_fit", "position", "flex_wrap", "text_align", "item_align", "visibility"],
)
@pytest.mark.parametrize("keyword", ["inherit", "initial", "unset", "revert"])
def test_css_wide_keywords_are_accepted_for_keyword_domain_properties(
    property_name: str, keyword: str
) -> None:
    utility = _utility(property_name, keyword)
    assert utility.source_value == keyword


@pytest.mark.parametrize("keyword", ["inherit", "initial", "unset", "revert"])
def test_css_wide_keywords_are_not_forced_onto_integer_properties(keyword: str) -> None:
    """order/column-count go through the shared transport length-token check,

    which this correction does not weaken -- a CSS-wide keyword is not a
    whole number, so it is rejected the same way "banana" would be for those
    two properties, matching what ``design/style_transport.py`` already
    enforces for every other length-shaped property.
    """

    with pytest.raises(ValidationError):
        _utility("order", keyword)
    with pytest.raises(ValidationError):
        _utility("column_count", keyword)


# --- integer sign / range edges ---------------------------------------------


@pytest.mark.parametrize("value", ["-1", "-100", "0", "1", "100"])
def test_order_accepts_any_signed_whole_number(value: str) -> None:
    assert _utility("order", value).source_value == value


@pytest.mark.parametrize("value", ["auto", "1", "999"])
def test_column_count_accepts_auto_or_a_positive_whole_number(value: str) -> None:
    assert _utility("column_count", value).source_value == value


@pytest.mark.parametrize("value", ["0", "-1", "-100"])
def test_column_count_rejects_nonpositive_values(value: str) -> None:
    with pytest.raises(ValidationError):
        _utility("column_count", value)


# --- keyword casing: normalized lookup, spelling preserved ------------------


@pytest.mark.parametrize(
    "property_name,value",
    [
        ("display", "Inline-Flex"),
        ("display", "GRID"),
        ("object_fit", "Cover"),
        ("position", "STATIC"),
        ("flex_wrap", "Wrap-Reverse"),
    ],
)
def test_keyword_matching_is_case_insensitive_but_spelling_is_preserved(
    property_name: str, value: str
) -> None:
    utility = _utility(property_name, value)
    # Lookup normalizes case (it would otherwise reject "Inline-Flex" outright,
    # since the domain tables are all lowercase), but the stored source_value
    # keeps the caller's original spelling/case exactly.
    assert utility.source_value == value


def test_keyword_casing_still_rejects_an_unrecognized_value_regardless_of_case() -> None:
    with pytest.raises(ValidationError):
        _utility("display", "BANANA")


def test_column_count_auto_keyword_is_case_sensitive_at_the_shared_transport_layer() -> None:
    """Unlike the closed-keyword domains above, "auto" for column-count is

    matched by ``design/style_transport.py``'s shared, case-sensitive
    ``_LENGTH_KEYWORDS`` set before this module's own column-count check ever
    runs. That transport layer is immutable shared infrastructure this
    correction does not touch, so this is a real, narrower limitation of the
    accepted grammar -- documented here rather than silently reinterpreted.
    """

    assert _utility("column_count", "auto").source_value == "auto"
    with pytest.raises(ValidationError):
        _utility("column_count", "AUTO")


# --- pre-existing injection / unsafe URL rejection is untouched -------------


@pytest.mark.parametrize(
    "property_name,value",
    [
        ("background_image", "javascript:alert(1)"),
        ("background_image", "url(javascript:alert(1))"),
        ("font_family", "</style><script>alert(1)</script>"),
        ("font_family", "@import url(evil.css)"),
        ("text_color", "red/*x*/"),
        ("display", "flex; background:url(evil)"),
    ],
)
def test_unsafe_or_injecting_values_remain_rejected(property_name: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _utility(property_name, value)


# --- legacy serialization is unchanged ---------------------------------------


def test_utility_and_payload_serialization_shape_is_unchanged() -> None:
    payload = AgencyStylePayload(
        version="1.0.0",
        utilities=[
            {"property": "order", "source_value": "2", "class_name": "cm-order-2"},
            {"property": "display", "source_value": "inline-flex", "class_name": "cm-d-inline-flex"},
        ],
    )
    dumped = payload.model_dump(mode="json")
    assert dumped == {
        "schema_version": "1.0",
        "version": "1.0.0",
        "utilities": [
            {
                "property": "order",
                "source_value": "2",
                "class_name": "cm-order-2",
                "important": False,
            },
            {
                "property": "display",
                "source_value": "inline-flex",
                "class_name": "cm-d-inline-flex",
                "important": False,
            },
        ],
    }
    assert json.loads(payload.model_dump_json()) == dumped
    assert style_utility_key(payload.utilities[0]) == "order:2"
    assert style_utility_key(payload.utilities[1]) == "display:inline-flex"


# --- schema parity ------------------------------------------------------------


def test_delivered_schema_matches_the_model_exactly() -> None:
    assert SCHEMA_PATH.is_file()
    on_disk = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert on_disk == AgencyStylePayload.model_json_schema()
