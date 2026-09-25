"""Carry accepted scoped-CSS declarations from a Composition Plan into
GrapesJS ``style_json``, and validate them as untrusted data at every
boundary that reads a serialized library plan.

Why an id selector, not the plan's ``css_scope`` string
---------------------------------------------------------
``CompositionPlanEntry.css_scope`` (``design/composition.py``) is a
project/section descendant selector like
``.https-source-test .design-section-home-services``. It is useful as a
human-readable, budget/report-facing label, and its shape is pinned by that
model's own validator, so this module leaves it alone.

But no rendered component ever carries a ``design-section-*`` class -- the
composed tree has no such wrapper -- so that string can never match
anything in real ``contentHtml``. This is the actual cause of the root
regression: an accepted style with nowhere to land.

Vanjaro already has a working, narrower convention for a per-element rule:
``block_compose.py``'s ``_apply_palette_background`` gives the styled
component a stable ``id`` and emits a single GrapesJS selector of
``type: 2`` (an id selector, see ``utils/grapesjs.render_styles``) naming
it. That selector is exactly what ``page_composition._namespace_styles``
already knows how to rewrite in lock-step with
``page_composition._namespace_components`` when a block lands on a page --
so reusing it, rather than inventing a second scoping scheme, is what makes
selectors survive page namespace rewriting for free. This module
replicates that small, proven shape rather than importing the private
helper, to keep this new transport self-contained.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from vanjaro_cli.design.composition import PlanPolicy
from vanjaro_cli.design.responsive_conditions import (
    BoundToken,
    condition_media_text,
    condition_sort_key,
    decode_condition_key,
)
from vanjaro_cli.design.style_translation import _CSS_PROPERTY_NAMES, _SAFE_CSS_VALUE
from vanjaro_cli.utils.image_links import is_safe_link_href

__all__ = [
    "DEFAULT_CSS_RULE_BUDGET",
    "StyleTransportError",
    "build_style_rules",
    "ensure_scoped_selector_id",
    "validate_style_payload",
]


class StyleTransportError(ValueError):
    """Raised when a serialized scoped-style payload is malformed or unsafe."""


# The translator (``design/style_translation.py``) is the single source of
# truth for which CSS properties it is willing to emit. Importing its
# mapping -- rather than retyping the list -- means this boundary check can
# never silently drift looser than the translator itself, without editing
# it.
_ALLOWED_PROPERTIES: frozenset[str] = frozenset(_CSS_PROPERTY_NAMES.values())

# Mirrors CompositionPlanEntry.css_scope's pattern in design/composition.py.
# Duplicated rather than imported because that pattern lives inside a
# pydantic Field() call, not a named constant.
_CSS_SCOPE_PATTERN = re.compile(r"^\.[a-z][a-z0-9-]*(?: \.[a-z][a-z0-9-]*)+$")

# A key is either bare (`font-family`, the unconditioned base rule), a
# legacy sample-breakpoint key (`tablet:min-height`, the agency's fixed
# per-breakpoint policy width -- see `_LEGACY_BREAKPOINT_BOUNDS` below), or
# an observed-condition key (`cond-max1023:min-height`, the real source
# width threshold `responsive_conditions.encode_condition_key` produced).
# The `cond` token's grammar is re-validated by `decode_condition_key`
# itself; this regex only bounds the digit count defensively.
_KEY_RE = re.compile(
    r"^(?:(desktop|tablet|mobile):|cond((?:-(?:min|max)\d{1,5})+):)?([a-z][a-z-]+)$"
)

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_URL_RE = re.compile(r"url\(\s*([^)]*)\)", re.IGNORECASE)
_DANGEROUS_SUBSTRINGS = ("javascript:", "vbscript:", "expression(", "@import")

# ``render_styles`` (utils/grapesjs.py) writes a value verbatim into
# ``prop:value`` CSS text, which page composition then embeds verbatim
# inside a visitor-facing HTML ``<style>`` element -- no HTML escaping and
# no CSS-escape decoding happens anywhere on that path. The only characters
# that can move the HTML tokenizer's raw-text scan for a literal
# ``</style`` (or open a new ``<script>``/``<img>`` element) are literal
# ``<``/``>`` themselves; the HTML tokenizer does not understand CSS syntax,
# so it is not fooled by a CSS comment (``/* ... */``) wrapped around them --
# the characters are still there, byte for byte. Rejecting the raw
# characters is therefore both necessary and sufficient, and it is
# inherently case-insensitive since ``<``/``>`` have no case.
_HTML_BREAKOUT_CHARS = re.compile(r"[<>]")

# CSS backslash escapes (e.g. ``\3c `` for ``<``, or ``jav\61script:`` for
# ``javascript:``) are decoded by a real CSS/URL-token parser but are inert
# to the HTML tokenizer above and to the plain substring checks below, so a
# value that survives ``_DANGEROUS_SUBSTRINGS``/``is_safe_link_href`` in its
# raw escaped form could still decode to a forbidden scheme or sequence in a
# browser. CSS comments are similarly inert to the HTML tokenizer and serve
# no purpose in any of the supported property values this transport emits.
# None of font-family/color/length/background values legitimately need
# either construct, so both are rejected outright rather than decoded and
# re-checked.
_CSS_ESCAPE_OR_COMMENT = re.compile(r"\\|/\*|\*/")

# Properties whose value is a length, a bare number, or one of a short set
# of layout keywords. Validated token-by-token (padding/margin can carry up
# to four) so an "invalid unit" is rejected instead of silently shipped.
_LENGTH_PROPERTIES: frozenset[str] = frozenset(
    {
        "font-size",
        "font-weight",
        "line-height",
        "letter-spacing",
        "width",
        "height",
        "min-height",
        "max-width",
        "margin",
        "padding",
        "row-gap",
        "column-gap",
        "border-radius",
        "opacity",
        "order",
        "column-count",
        "rotate",
    }
)
_LENGTH_TOKEN = re.compile(r"^-?\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|vmin|vmax|deg)?$")
_LENGTH_KEYWORDS = frozenset({"auto", "normal", "none", "0"})

# The agency's reviewed fallback policy for a property with no proven source
# condition (see `style_translation._scoped_css_key`): the same canonical
# capture viewports already used across design/figma_adapter.py,
# design/responsive_merge.py, design/html_ownership.py and
# design/visual_gate.py (DESKTOP=1440, TABLET=768, MOBILE=390), applied as
# fixed max-width thresholds. This is an explicit *interpretation*, not an
# observation -- a property with an actual acquired source condition never
# reaches this mapping at all (see `_scoped_css_key`'s condition-key path).
_LEGACY_BREAKPOINT_BOUNDS: dict[str, tuple[BoundToken, ...]] = {
    "desktop": (),
    "tablet": (("max_width", 768),),
    "mobile": (("max_width", 390),),
}

# Defensive ceiling for untrusted payloads. Mirrors PlanPolicy's own
# default budget rather than a separately maintained number; a plan built
# with a non-default policy is still capped here, since the emitted library
# plan format carries no policy reference to thread through.
DEFAULT_CSS_RULE_BUDGET: int = PlanPolicy().css_rule_budget


def _parse_key(key: str) -> tuple[tuple[BoundToken, ...], str]:
    if not isinstance(key, str):
        raise StyleTransportError(f"style declaration key {key!r} must be a string")
    match = _KEY_RE.fullmatch(key)
    if match is None:
        raise StyleTransportError(
            f"style declaration key {key!r} is not a valid "
            "'[breakpoint:|cond-<bounds>:]property' key"
        )
    breakpoint_token, condition_token, css_property = match.groups()
    if css_property not in _ALLOWED_PROPERTIES:
        raise StyleTransportError(
            f"style property {css_property!r} is not a recognized translator output property"
        )
    if condition_token is not None:
        try:
            bounds = decode_condition_key(condition_token)
        except ValueError as exc:
            raise StyleTransportError(
                f"style declaration key {key!r} has an invalid condition: {exc}"
            ) from exc
    elif breakpoint_token:
        bounds = _LEGACY_BREAKPOINT_BOUNDS[breakpoint_token]
    else:
        bounds = ()
    return bounds, css_property


def _validate_length_tokens(css_property: str, body: str) -> None:
    tokens = body.split()
    if not tokens:
        raise StyleTransportError(f"style value for {css_property!r} must not be blank")
    for token in tokens:
        if token in _LENGTH_KEYWORDS:
            continue
        if not _LENGTH_TOKEN.fullmatch(token):
            raise StyleTransportError(
                f"style value for {css_property!r} has an unrecognized unit: {token!r}"
            )


def _validate_value(css_property: str, value: str) -> str:
    if not isinstance(value, str):
        raise StyleTransportError(f"style value for {css_property!r} must be a string")
    text = value.strip()
    if not text:
        raise StyleTransportError(f"style value for {css_property!r} must not be blank")
    if _CONTROL_CHARS.search(text):
        raise StyleTransportError(f"style value for {css_property!r} contains control characters")
    if _HTML_BREAKOUT_CHARS.search(text):
        raise StyleTransportError(
            f"style value for {css_property!r} contains HTML-breaking syntax"
        )
    if _CSS_ESCAPE_OR_COMMENT.search(text):
        raise StyleTransportError(
            f"style value for {css_property!r} contains CSS escape or comment syntax"
        )
    if not _SAFE_CSS_VALUE.fullmatch(text):
        raise StyleTransportError(f"style value for {css_property!r} contains unsafe CSS syntax")
    lowered = text.casefold()
    for token in _DANGEROUS_SUBSTRINGS:
        if token in lowered:
            raise StyleTransportError(f"style value for {css_property!r} is rejected as unsafe")
    for raw_url in _URL_RE.findall(text):
        candidate = raw_url.strip().strip("'\"")
        if candidate and not is_safe_link_href(candidate):
            raise StyleTransportError(
                f"style value for {css_property!r} references an unsafe URL"
            )

    body = text
    if lowered.endswith("!important"):
        body = text[: -len("!important")].strip()
        if body.endswith("!"):
            body = body[:-1].strip()

    if css_property in _LENGTH_PROPERTIES:
        _validate_length_tokens(css_property, body)
    return text


def validate_style_payload(
    scope: str | None,
    declarations: dict[str, Any],
    *,
    budget: int | None = None,
) -> dict[tuple[BoundToken, ...], dict[str, str]]:
    """Validate an untrusted scoped-style payload and group it by condition.

    Raises ``StyleTransportError`` with an actionable, non-echoing-of-raw-
    payload message on the first problem found: an unrecognized property, an
    unsafe or malformed value, an invalid breakpoint/condition, a
    missing/malformed scope, or a rule count over budget. Each returned key
    is a tuple of width bounds -- empty for the unconditioned base rule --
    covering both the legacy sample-breakpoint policy keys and an observed
    source condition's exact bounds; see ``_parse_key``.
    """

    if not isinstance(declarations, dict) or not declarations:
        raise StyleTransportError("style declarations must be a non-empty object")
    if not isinstance(scope, str) or not scope.strip():
        raise StyleTransportError("a style scope is required when style declarations are present")
    if not _CSS_SCOPE_PATTERN.fullmatch(scope):
        raise StyleTransportError(f"style scope {scope!r} is not a client-safe scope selector")

    effective_budget = DEFAULT_CSS_RULE_BUDGET if budget is None else budget
    if len(declarations) > effective_budget:
        raise StyleTransportError(
            f"scoped CSS rule count {len(declarations)} exceeds budget {effective_budget}"
        )

    buckets: dict[tuple[BoundToken, ...], dict[str, str]] = {}
    for raw_key, raw_value in declarations.items():
        bounds, css_property = _parse_key(raw_key)
        safe_value = _validate_value(css_property, raw_value)
        buckets.setdefault(bounds, {})[css_property] = safe_value
    return buckets


def ensure_scoped_selector_id(component: dict[str, Any], section_key: str) -> str:
    """Return a stable id for ``component``, generating one if it has none.

    Reuses whatever id the template/composition already assigned so a
    style rule never fights an existing selector target; the id is
    otherwise derived deterministically from ``section_key`` so repeated
    composition of an unchanged plan produces byte-identical output
    (composed-block idempotency and hash stability depend on this -- a
    random id would make ``desired_hash`` churn on every rebuild).
    """

    attributes = component.setdefault("attributes", {})
    existing = attributes.get("id")
    if isinstance(existing, str) and existing:
        return existing
    derived = f"vj-style-{hashlib.sha256(section_key.encode('utf-8')).hexdigest()[:10]}"
    attributes["id"] = derived
    return derived


def build_style_rules(
    element_id: str, buckets: dict[tuple[BoundToken, ...], dict[str, str]]
) -> list[dict[str, Any]]:
    """Build GrapesJS style rules targeting ``element_id`` by id selector.

    One rule per non-empty condition bucket, ordered by
    ``responsive_conditions.condition_sort_key`` so the narrowest/most
    specific condition is last in source order and wins the cascade against
    an overlapping wider one -- whether that condition came from the fixed
    legacy breakpoint policy or an exact observed source threshold.
    """

    rules: list[dict[str, Any]] = []
    for bounds in sorted(buckets, key=condition_sort_key):
        style = buckets.get(bounds)
        if not style:
            continue
        rule: dict[str, Any] = {
            "selectors": [
                {
                    "name": element_id,
                    "label": element_id,
                    "type": 2,
                    "active": True,
                    "private": True,
                    "protected": False,
                }
            ],
            "style": dict(sorted(style.items())),
        }
        media_text = condition_media_text(bounds)
        if media_text:
            rule["mediaText"] = media_text
            rule["atRuleType"] = "media"
        rules.append(rule)
    return rules
