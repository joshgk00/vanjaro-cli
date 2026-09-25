"""Deterministic title selection for Figma hero-style sections.

``_refine_section_content`` in ``figma_adapter`` has to decide, after every
descendant of a section is available, which text element is the headline.
Figma files frequently omit ``style.fontSize`` (components, some auto-layout
exports) or give several candidates the same size, and Figma layer order is
often not reading order. When font evidence cannot separate the candidates,
this module falls back to explicit semantic layer names (``figma_node_name``)
and geometric reading order (top-to-bottom, then left-to-right, then document
order) rather than the longest string. A strong font-size hierarchy is still
the primary signal and is preferred whenever it uniquely identifies a title.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from vanjaro_cli.design.models import BoundingBox, ContentElement

_TITLE_NAME = re.compile(r"\b(headline|heading|title)\b", re.IGNORECASE)
_NON_TITLE_NAME = re.compile(
    r"\b(subtitle|eyebrow|kicker|tag|body|description|caption|label|"
    r"quote|author|action|button|cta)\b",
    re.IGNORECASE,
)


def _font_size(element: ContentElement) -> float:
    try:
        return float(element.attributes.get("font_size") or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_observed_font_size(element: ContentElement) -> bool:
    return element.attributes.get("font_size") is not None


def _node_name(element: ContentElement) -> str:
    return str(element.attributes.get("figma_node_name", ""))


def _bounds(element: ContentElement) -> BoundingBox | None:
    return element.provenance[0].bounds if element.provenance else None


def _reading_position(element: ContentElement) -> tuple[float, float, int]:
    box = _bounds(element)
    if box is not None:
        return (box.y, box.x, element.order)
    return (float(element.order), 0.0, element.order)


def select_hero_title(candidates: Sequence[ContentElement]) -> ContentElement:
    """Pick the title among a section's text candidates.

    Preference order: a font size that uniquely dominates the others, then
    an explicit title-ish layer name (``Headline``, ``Heading``, ``Title``),
    then geometric reading order among whatever is left once explicitly
    non-title names (``Body``, ``Subtitle``, ``Eyebrow``, ...) are set
    aside. This intentionally ignores each element's pre-assigned
    ``ContentKind``/``role`` and string length, since the first text child
    in traversal order can already be misclassified as a heading and a long
    paragraph should never outrank an explicitly named headline.
    """

    if not candidates:
        raise ValueError("select_hero_title requires at least one candidate")

    pool: Sequence[ContentElement] = candidates
    if all(_has_observed_font_size(element) for element in candidates):
        # A size measured for one candidate is only comparable to another
        # measured size; an unobserved candidate could be any size, so this
        # shortcut is only safe once every candidate actually reports one.
        font_sizes = {element.id: _font_size(element) for element in candidates}
        max_font = max(font_sizes.values())
        dominant = [element for element in candidates if font_sizes[element.id] == max_font]
        if len(dominant) == 1:
            return dominant[0]
        pool = dominant

    named_title = [element for element in pool if _TITLE_NAME.search(_node_name(element))]
    if named_title:
        pool = named_title
    else:
        non_title_ids = {
            element.id for element in pool if _NON_TITLE_NAME.search(_node_name(element))
        }
        unnamed = [element for element in pool if element.id not in non_title_ids]
        if unnamed:
            pool = unnamed

    return min(pool, key=_reading_position)
