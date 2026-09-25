"""New versioned, typed executable style payload for opt-in agency packs.

A utility declares a ``(property, source_value)`` pair and the one CSS class
name it targets. There is no separate raw-declaration field, so a payload can
never claim a class produces CSS other than what its own property/value pair
validates to -- the declaration is always *derived*, at read time, from the
same canonical CSS property mapping and safety validator
``design/style_translation.py`` and ``design/style_transport.py`` already
trust for source-derived styles (see ``style_context.py``). This module
re-uses those tables directly rather than defining a second, independently
maintained property map.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from vanjaro_cli.design.models import StyleProperty
from vanjaro_cli.design.style_transport import StyleTransportError, _validate_value
from vanjaro_cli.design.style_translation import _CSS_PROPERTY_NAMES
from vanjaro_cli.utils.semver import validate_semver

__all__ = ["AgencyStylePayload", "AgencyStyleUtility", "style_utility_key"]


_CLASS_NAME_PATTERN = r"^[a-z][a-z0-9-]*$"

# ``_validate_value`` only checks that a value is *safe transport text* for a
# CSS property (no breakout, no unsafe URL, a recognized unit if the
# property is length-shaped) -- it does not know that ``order`` is a whole
# number or that ``display`` only has a handful of legitimate keywords, so a
# safe-but-meaningless value like "order: 1.5" or "display: banana" would
# otherwise pass through as a defined, class-bound "executable" utility.
#
# The checks below are deliberately *not* built from ``_UTILITY_VALUES``
# (style_translation.py's source-value -> Bootstrap/Vanjaro utility-class
# table). That table records which keyword values this codebase currently
# ships a reusable platform utility class for -- a target-availability fact
# -- not which values are valid CSS for the property. A value can be
# perfectly valid CSS (``display: inline-flex``, ``position: static``) with
# no platform utility mapped to it at all; an agency pack is exactly the
# place such a value should still be definable. Each domain below is instead
# the standard keyword set for that property drawn from its own CSS
# specification, so it stays correct even as ``_UTILITY_VALUES`` gains or
# loses entries for unrelated (Bootstrap availability) reasons.
_CSS_WIDE_KEYWORDS: frozenset[str] = frozenset(
    {"inherit", "initial", "unset", "revert", "revert-layer"}
)

_DISPLAY_KEYWORDS: frozenset[str] = frozenset(
    {
        "none",
        "block",
        "inline",
        "inline-block",
        "flex",
        "inline-flex",
        "grid",
        "inline-grid",
        "table",
        "inline-table",
        "table-row",
        "table-row-group",
        "table-header-group",
        "table-footer-group",
        "table-column",
        "table-column-group",
        "table-cell",
        "table-caption",
        "list-item",
        "contents",
        "flow-root",
    }
)
_OBJECT_FIT_KEYWORDS: frozenset[str] = frozenset(
    {"fill", "contain", "cover", "none", "scale-down"}
)
_POSITION_KEYWORDS: frozenset[str] = frozenset(
    {"static", "relative", "absolute", "fixed", "sticky"}
)
_FLEX_WRAP_KEYWORDS: frozenset[str] = frozenset({"nowrap", "wrap", "wrap-reverse"})
_FLEX_DIRECTION_KEYWORDS: frozenset[str] = frozenset(
    {"row", "row-reverse", "column", "column-reverse"}
)
_TEXT_ALIGN_KEYWORDS: frozenset[str] = frozenset(
    {"left", "right", "center", "justify", "start", "end"}
)
_ALIGN_ITEMS_KEYWORDS: frozenset[str] = frozenset(
    {
        "flex-start",
        "flex-end",
        "center",
        "baseline",
        "stretch",
        "start",
        "end",
        "self-start",
        "self-end",
        "normal",
    }
)
_VISIBILITY_KEYWORDS: frozenset[str] = frozenset({"visible", "hidden", "collapse"})

# Keyed by ``StyleProperty`` (the model field's own type) rather than the CSS
# property string, so each entry is one authoritative domain per source enum
# member -- exactly the closed-keyword properties this module can validate a
# fixed grammar for. Properties with an open-ended CSS grammar (colors,
# lengths, ``transform``, ``box-shadow``, ...) are intentionally absent: for
# those, ``_validate_value``'s transport-safety check is the whole of what
# this module can honestly claim to verify, per the module docstring above.
_CSS_KEYWORD_DOMAINS: dict[StyleProperty, frozenset[str]] = {
    StyleProperty.DISPLAY: _DISPLAY_KEYWORDS,
    StyleProperty.OBJECT_FIT: _OBJECT_FIT_KEYWORDS,
    StyleProperty.POSITION: _POSITION_KEYWORDS,
    StyleProperty.FLEX_WRAP: _FLEX_WRAP_KEYWORDS,
    StyleProperty.FLEX_DIRECTION: _FLEX_DIRECTION_KEYWORDS,
    StyleProperty.TEXT_ALIGN: _TEXT_ALIGN_KEYWORDS,
    StyleProperty.ITEM_ALIGN: _ALIGN_ITEMS_KEYWORDS,
    StyleProperty.VISIBILITY: _VISIBILITY_KEYWORDS,
}

# ``order`` accepts any signed whole number (CSS Flexbox ``<integer>``).
# ``column-count`` accepts ``auto`` or a positive whole number (CSS
# Multi-column ``auto | <integer>``, and a zero or negative column count has
# no rendering meaning) -- a distinct enough grammar from ``order`` that it
# is handled as its own case rather than folded into one shared set.
_SIGNED_INTEGER_TOKEN = re.compile(r"^-?\d+$")
_POSITIVE_INTEGER_TOKEN = re.compile(r"^\d+$")


class _StyleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AgencyStyleUtility(_StyleModel):
    """One executable utility: a validated CSS declaration bound to one class."""

    property: StyleProperty
    source_value: str = Field(min_length=1)
    class_name: str = Field(pattern=_CLASS_NAME_PATTERN)
    important: bool = False

    @field_validator("source_value")
    @classmethod
    def _non_blank_source_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_value must not be blank")
        return value

    @model_validator(mode="after")
    def _safe_declaration(self) -> "AgencyStyleUtility":
        # ``_CSS_PROPERTY_NAMES`` is exhaustive over ``StyleProperty`` today,
        # but this stays a real lookup (not an assumption) so a future
        # property added to one enum without the other fails closed here
        # instead of emitting an unmapped declaration.
        css_property = _CSS_PROPERTY_NAMES.get(self.property)
        if css_property is None:
            raise ValueError(
                f"{self.property.value!r} has no canonical CSS property mapping"
            )
        body = self.source_value.strip()
        candidate = f"{body} !important" if self.important else body
        try:
            _validate_value(css_property, candidate)
        except StyleTransportError as exc:
            raise ValueError(str(exc)) from exc

        folded = body.casefold()
        if self.property is StyleProperty.ORDER:
            if not _SIGNED_INTEGER_TOKEN.fullmatch(body):
                raise ValueError(
                    f"{css_property!r} requires a signed whole-number source_value, "
                    f"not {body!r}"
                )
        elif self.property is StyleProperty.COLUMN_COUNT:
            is_positive_integer = _POSITIVE_INTEGER_TOKEN.fullmatch(body) and int(body) > 0
            if folded != "auto" and not is_positive_integer:
                raise ValueError(
                    f"{css_property!r} requires 'auto' or a positive whole-number "
                    f"source_value, not {body!r}"
                )
        else:
            keyword_domain = _CSS_KEYWORD_DOMAINS.get(self.property)
            if (
                keyword_domain is not None
                and folded not in keyword_domain
                and folded not in _CSS_WIDE_KEYWORDS
            ):
                raise ValueError(
                    f"{body!r} is not a supported CSS value for {css_property!r}"
                )
        return self


def style_utility_key(utility: AgencyStyleUtility) -> str:
    """Normalized ``property:value`` key, matching ``style_translation``'s own.

    Mirrors ``_agency_decision``'s ``f"{property.value}:{value.casefold()}"``
    key in ``design/style_translation.py`` exactly, so an agency utility here
    is addressable the same way a source-observed value is. Only the value is
    case-folded -- the property name is already the enum's fixed lowercase
    token -- so unrelated case-sensitive content (like the class name) is
    never silently altered.
    """

    return f"{utility.property.value}:{utility.source_value.strip().casefold()}"


class AgencyStylePayload(_StyleModel):
    schema_version: Literal["1.0"] = "1.0"
    version: str
    utilities: tuple[AgencyStyleUtility, ...] = ()

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        return validate_semver(value)

    @model_validator(mode="after")
    def _no_conflicting_definitions(self) -> "AgencyStylePayload":
        keys = [style_utility_key(utility) for utility in self.utilities]
        if len(keys) != len(set(keys)):
            raise ValueError(
                "style utilities must not declare conflicting normalized "
                "property/value keys"
            )
        class_names = [utility.class_name for utility in self.utilities]
        if len(class_names) != len(set(class_names)):
            raise ValueError(
                "style utilities must not reuse a class name across definitions"
            )
        return self
