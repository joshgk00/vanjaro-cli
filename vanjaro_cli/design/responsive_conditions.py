"""Pure helpers for source-backed responsive condition transport.

Independent of browser I/O: this module defines the plain data shape for one
CSS declaration's cascade-relevant evidence (``RawDeclaration``, produced by
``html_media_evidence.py`` from real CSSOM acquisition), resolves which
declaration wins the cascade for a sampled breakpoint, and encodes/decodes
the compact condition key used to carry an exact bounded-width condition
through the existing ``dict[str, str]`` scoped-style transport
(``design/style_translation.py`` -> ``design/composition.py`` ->
``design/planner.py`` -> ``design/style_transport.py``) without changing that
transport's shape.

A condition key looks like ``cond-max1023:min-height`` (one bound) or
``cond-min480-max1023:min-height`` (two bounds, a nested/intersecting
range) -- deterministically ordered (min bounds before max, ascending
threshold) so the same logical condition always encodes to the same string,
which both hash stability and dict-key de-duplication depend on.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from vanjaro_cli.design.models import (
    ConditionBound,
    Provenance,
    ResponsiveCondition,
    ResponsiveConditionKind,
    ResponsiveConditionStatus,
)

__all__ = [
    "BoundToken",
    "MAX_THRESHOLD_PX",
    "RawDeclaration",
    "bounds_match_width",
    "condition_media_text",
    "condition_sort_key",
    "decode_condition_key",
    "encode_condition_key",
    "resolve_property_condition",
    "to_bound_tokens",
]

# (kind, threshold_px); kind is "min_width" | "max_width". Plain tuples, not
# the pydantic ConditionBound, so style_transport.py -- which validates an
# untrusted serialized library plan and must stay dependency-light -- never
# needs to import the Design Document model layer just to parse a key.
BoundToken = tuple[str, int]

MAX_THRESHOLD_PX = 20000

_CONDITION_TOKEN_RE = re.compile(r"-(min|max)(\d{1,5})")


@dataclass(frozen=True, slots=True)
class RawDeclaration:
    """One accessible CSS declaration considered for cascade resolution.

    ``bounds`` is empty for an unconditioned (always-applicable) rule, and
    also empty when ``supported`` is ``False`` and no bound could be parsed
    at all. ``specificity`` is ``(id_count, class_count, type_count)`` for
    the one selector part (from a comma-separated ``selectorText``) that
    matched the target element. ``order`` is the declaration's position
    across the whole accessible stylesheet set, in document order, used to
    break cascade ties the same way a browser does (last wins).
    """

    css_property: str
    value: str
    important: bool
    order: int
    specificity: tuple[int, int, int]
    bounds: tuple[BoundToken, ...]
    supported: bool
    selector: str
    reason: str | None = None


def bounds_match_width(bounds: Sequence[BoundToken], width_px: int) -> bool:
    """Whether every bound in ``bounds`` is satisfied at ``width_px``.

    An empty ``bounds`` (an unconditioned/base declaration) is always
    satisfied -- there is no width restriction to check.
    """

    return all(
        width_px >= threshold if kind == "min_width" else width_px <= threshold
        for kind, threshold in bounds
    )


def condition_sort_key(bounds: Sequence[BoundToken]) -> tuple[int, int]:
    """Ordering key so a narrower/more-specific condition sorts later.

    Mirrors real mobile-first authoring: a base rule (no bounds) sorts
    first; among ``max-width`` rules, the smaller threshold (the narrower,
    more specific override) sorts last; among ``min-width`` rules, the
    larger threshold sorts last. Emitting rules in this order lets a real
    browser's own last-wins cascade tie-break reproduce the source's
    intended precedence for any two conditions that can both match one
    real viewport width.
    """

    lower = max((t for k, t in bounds if k == "min_width"), default=0)
    upper = min((t for k, t in bounds if k == "max_width"), default=MAX_THRESHOLD_PX + 1)
    return (lower, -upper)


def condition_media_text(bounds: Sequence[BoundToken]) -> str | None:
    """Render ``bounds`` as an ``@media`` condition, or ``None`` for the base rule."""

    if not bounds:
        return None
    ordered = sorted(bounds, key=lambda pair: (0 if pair[0] == "min_width" else 1, pair[1]))
    clauses = [
        f"(min-width: {threshold}px)" if kind == "min_width" else f"(max-width: {threshold}px)"
        for kind, threshold in ordered
    ]
    return " and ".join(clauses)


def _validate_bounds(bounds: Sequence[BoundToken]) -> tuple[BoundToken, ...]:
    if not bounds or len(bounds) > 2:
        raise ValueError("a condition must declare one or two width bounds")
    kinds = [kind for kind, _ in bounds]
    if len(set(kinds)) != len(kinds):
        raise ValueError("a condition cannot repeat the same bound kind")
    for kind, threshold in bounds:
        if kind not in ("min_width", "max_width"):
            raise ValueError(f"unsupported condition bound kind {kind!r}")
        if not (0 < threshold <= MAX_THRESHOLD_PX):
            raise ValueError(f"condition threshold {threshold}px is out of range")
    lower = max((t for k, t in bounds if k == "min_width"), default=0)
    upper = min((t for k, t in bounds if k == "max_width"), default=MAX_THRESHOLD_PX + 1)
    if lower >= upper:
        raise ValueError(f"condition bounds {bounds!r} describe an empty width range")
    return tuple(sorted(bounds, key=lambda pair: (0 if pair[0] == "min_width" else 1, pair[1])))


def encode_condition_key(bounds: Sequence[BoundToken]) -> str:
    """Return the canonical ``cond-...`` token for ``bounds``.

    Raises ``ValueError`` for anything outside the supported grammar (zero
    or more than two bounds, a repeated kind, an out-of-range threshold, or
    an empty resulting width range) -- the same validation
    ``decode_condition_key`` applies, so a round trip never silently
    normalizes an invalid condition into a valid one.
    """

    ordered = _validate_bounds(bounds)
    tokens = "".join(
        f"-min{threshold}" if kind == "min_width" else f"-max{threshold}"
        for kind, threshold in ordered
    )
    return f"cond{tokens}"


def decode_condition_key(condition_token: str) -> tuple[BoundToken, ...]:
    """Parse the ``-min480-max1023``-shaped suffix captured after ``cond``.

    Raises ``ValueError`` for anything malformed or unsupported -- callers
    at an untrusted boundary (``style_transport.validate_style_payload``)
    are expected to translate that into their own fail-closed error type.
    """

    matches = _CONDITION_TOKEN_RE.findall(condition_token)
    consumed = sum(len(prefix) + len(digits) + 1 for prefix, digits in matches)
    if not matches or consumed != len(condition_token):
        raise ValueError(f"malformed condition token {condition_token!r}")
    bounds = tuple(
        ("min_width" if prefix == "min" else "max_width", int(digits))
        for prefix, digits in matches
    )
    return _validate_bounds(bounds)


def to_bound_tokens(condition: ResponsiveCondition) -> tuple[BoundToken, ...]:
    """Convert a typed ``ResponsiveCondition``'s bounds to plain tokens."""

    return tuple((bound.kind.value, bound.threshold_px) for bound in condition.bounds)


def _cascade_key(declaration: RawDeclaration) -> tuple[bool, tuple[int, int, int], int]:
    return (declaration.important, declaration.specificity, declaration.order)


def resolve_property_condition(
    declarations: Sequence[RawDeclaration],
    css_property: str,
    query_width_px: int,
    computed_value: str,
    *,
    provenance: Sequence[Provenance] = (),
) -> ResponsiveCondition | None:
    """Resolve which declaration set ``css_property`` at ``query_width_px``.

    Returns ``None`` when no accessible declaration touches ``css_property``
    at all -- a pure sample with no CSS evidence gathered, not a gap to
    report. Returns a ``ResponsiveCondition`` with ``status=UNRESOLVED`` (and
    an actionable ``reason``) when evidence exists but correct
    winning-rule attribution cannot be proved: an unsupported media/
    container expression could win the cascade for this property, no
    declaration's condition is satisfied at ``query_width_px``, the winning
    declaration carries no media condition at all, or its value does not
    match ``computed_value``. Returns ``status=OBSERVED`` only when a
    media-conditioned declaration is proven to win the cascade among every
    declaration whose bounds are satisfied at ``query_width_px``, and its
    value matches the sample.
    """

    relevant = [item for item in declarations if item.css_property == css_property]
    if not relevant:
        return None

    unsupported = [item for item in relevant if not item.supported]
    eligible_supported = [
        item
        for item in relevant
        if item.supported and (not item.bounds or bounds_match_width(item.bounds, query_width_px))
    ]

    best_supported = max(eligible_supported, key=_cascade_key) if eligible_supported else None
    best_unsupported = max(unsupported, key=_cascade_key) if unsupported else None

    if best_unsupported is not None and (
        best_supported is None or _cascade_key(best_unsupported) > _cascade_key(best_supported)
    ):
        return ResponsiveCondition(
            bounds=[],
            status=ResponsiveConditionStatus.UNRESOLVED,
            rule_order=best_unsupported.order,
            selector=best_unsupported.selector,
            reason=(
                best_unsupported.reason
                or "an unsupported media/container expression may win the cascade for this property"
            ),
            provenance=list(provenance),
        )

    if best_supported is None:
        return ResponsiveCondition(
            bounds=[],
            status=ResponsiveConditionStatus.UNRESOLVED,
            rule_order=relevant[-1].order,
            selector=relevant[-1].selector,
            reason="no accessible declaration's condition is satisfied at the sampled width",
            provenance=list(provenance),
        )

    if not best_supported.bounds:
        return ResponsiveCondition(
            bounds=[],
            status=ResponsiveConditionStatus.UNRESOLVED,
            rule_order=best_supported.order,
            selector=best_supported.selector,
            reason=(
                "the winning declaration for this value has no media condition; "
                "the sampled change cannot be attributed to a width threshold"
            ),
            provenance=list(provenance),
        )

    normalized_sample = " ".join(str(computed_value).split()).casefold()
    normalized_winner = " ".join(best_supported.value.split()).casefold()
    if normalized_sample != normalized_winner:
        return ResponsiveCondition(
            bounds=[],
            status=ResponsiveConditionStatus.UNRESOLVED,
            rule_order=best_supported.order,
            selector=best_supported.selector,
            reason=(
                f"the resolved winning declaration value {best_supported.value!r} does not "
                f"match the sampled computed value {computed_value!r}"
            ),
            provenance=list(provenance),
        )

    return ResponsiveCondition(
        bounds=[
            ConditionBound(kind=ResponsiveConditionKind(kind), threshold_px=threshold)
            for kind, threshold in best_supported.bounds
        ],
        status=ResponsiveConditionStatus.OBSERVED,
        important=best_supported.important,
        rule_order=best_supported.order,
        selector=best_supported.selector,
        provenance=list(provenance),
    )
